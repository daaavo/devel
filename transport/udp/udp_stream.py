
import time
import cStringIO
import struct

from twisted.internet import reactor

from logs import lg

from lib import udp

import udp_session

#------------------------------------------------------------------------------ 

"""
Datagram Format

[Data] packet

bytes:
  0        software version number
  1        command identifier, see ``lib.udp`` module
  2-5      stream_id 
  6-9      total data size to be transferred, peer must know when to stop receiving
  10-13    block_id, outgoing blocks are counted from 1
  from 14  payload data   
  
"""

UDP_DATAGRAM_SIZE = 508
BLOCK_SIZE = UDP_DATAGRAM_SIZE - 14 

BLOCKS_PER_ACK = 16

MAX_BUFFER_SIZE = 64*1024
BUFFER_SIZE = BLOCK_SIZE * BLOCKS_PER_ACK # BLOCK_SIZE * int(float(BLOCKS_PER_ACK)*0.8) - 20% extra space in ack packet

RTT_MIN_LIMIT = 0.002
RTT_MAX_LIMIT = 0.5

#------------------------------------------------------------------------------ 

# _Streams = {}
# _DeadStreams = set()

#------------------------------------------------------------------------------ 

# def streams():
#     global _Streams
#     return _Streams


# def dead_streams():
#     global _DeadStreams
#     return _DeadStreams


#def command_received(command, datagram, inp, address):
#    if command == udp.CMD_DATA:
#        try:
#            stream_id = struct.unpack('i', inp.read(4))[0]
#            data_size = struct.unpack('i', inp.read(4))[0]
#        except:
#            lg.exc()
#            return True
#        stream = streams().get(stream_id, None)
#        if stream:
#            stream.block_received(inp)
#            return True
#    elif command == udp.CMD_ACK:
#        try:
#            stream_id = struct.unpack('i', inp.read(4))[0]
#        except:
#            lg.exc()
#            return True
#        stream = streams().get(stream_id, None)
#        if stream:
#            stream.ack_received(inp)
#            return True
#    elif command in (udp.CMD_ALIVE, udp.CMD_GREETING, udp.CMD_PING,):
#        sess = udp_session.get(address)
#        if sess:
#            sess.automat('datagram-received', (datagram, address))
#            return True
#    return False

#------------------------------------------------------------------------------ 

class UDPStream():
    def __init__(self, stream_id, consumer, producer):
        self.stream_id = stream_id
        self.consumer = consumer
        self.producer = producer
        self.consumer.stream = self
        # self.send_data_packet_func = send_data_packet_func
        # self.send_ack_packet_func = send_ack_packet_func
        # self.received_raw_data_callback = received_raw_data_callback
        # self.sent_raw_data_callback = sent_raw_data_callback
        self.output_buffer_size = 0
        self.output_blocks = {}
        # self.output_blocks_acks = []
        self.output_block_id = 0
        self.output_blocks_counter = 0
        self.output_acks_counter = 0
        self.input_blocks = {}
        self.input_block_id = 0
        self.input_blocks_counter = 0
        self.input_acks_counter = 0
        self.input_duplicated_blocks = 0
        self.input_duplicated_bytes = 0
        self.blocks_to_ack = set()
        self.bytes_in = 0
        self.bytes_in_acks = 0
        self.bytes_sent = 0
        self.bytes_acked = 0
        self.resend_bytes = 0
        self.last_ack_moment = 0
        self.last_ack_received_time = 0
        self.last_block_received_time = 0
        self.rtt_avarage = RTT_MIN_LIMIT
        self.rtt_acks_counter = 1.0
        self.resend_task = None
        self.resend_inactivity_counter = 0
        self.resend_counter = 0
        self.limit_send_bytes_per_sec = 1 * 125000 # 1 Mbps = 125000 B/s ~ 122 KB/s 
        self.creation_time = time.time()
        # streams()[self.stream_id] = self
        # lg.out(18, 'udp_stream.__init__ %d' % self.stream_id)
        
    def __del__(self):
        """
        """
        # lg.out(18, 'udp_stream.__del__ %d' % self.stream_id)
        
    def close(self):
#        lg.out(18, 'udp_stream.close %d in:%d|%d acks:%d|%d dups:%d|%d out:%d|%d|%d' % (
#            self.stream_id, # len(streams()), 
#            self.input_blocks_counter, self.bytes_in,
#            self.output_acks_counter, self.bytes_in_acks,
#            self.input_duplicated_blocks, self.input_duplicated_bytes,
#            self.output_blocks_counter, self.bytes_acked, self.resend_bytes,))
        # streams().pop(self.stream_id)
        self.stop_resending()
        self.consumer.stream = None
        self.consumer = None
        self.producer = None
        self.blocks_to_ack.clear()
        self.output_blocks.clear()
        # self.send_data_packet_func = None
        # self.send_ack_packet_func = None
        # self.received_raw_data_callback = None
        # self.sent_raw_data_callback = None
        
    def block_received(self, inpt):
        if self.consumer:
            block_id = struct.unpack('i', inpt.read(4))[0]
            data = inpt.read()
            if block_id in self.input_blocks.keys():
                self.input_duplicated_blocks += 1
                self.input_duplicated_bytes += len(data)
                print 'duplicated', block_id
            self.input_blocks[block_id] = data
            self.input_blocks_counter += 1
            self.bytes_in += len(data)
            self.blocks_to_ack.add(block_id)
            self.last_block_received_time = time.time() - self.creation_time
            eof_state = False
            # print 'block', block_id, self.bytes_in, block_id % BLOCKS_PER_ACK
            if block_id == self.input_block_id + 1:
                newdata = cStringIO.StringIO()
                newblocks = 0
                # print 'newdata',
                while True:
                    next_block_id = self.input_block_id + 1
                    try:
                        blockdata = self.input_blocks.pop(next_block_id)
                    except KeyError:
                        break
                    newdata.write(blockdata)
                    self.input_block_id = next_block_id
                    newblocks += 1
                    # print next_block_id,
                eof_state = self.consumer.on_received_raw_data(newdata.getvalue())
                newdata.close()
                # print 'received %d bytes in %d blocks, eof=%r' % (len(newdata), num_blocks, eof_state)
            # want to send the first ack asap
            if time.time() - self.last_ack_moment > RTT_MAX_LIMIT \
                or block_id % BLOCKS_PER_ACK == 1 \
                or eof_state:
                    # self.send_ack()
                    self.resend()
    
    def ack_received(self, inpt):
        if self.consumer:
            acks = 0
            eof = False
            raw_bytes = ''
            while True:
                raw_bytes = inpt.read(4)
                if not raw_bytes:
                    break
                block_id = struct.unpack('i', raw_bytes)[0]
                acks += 1
                try:
                    outblock = self.output_blocks.pop(block_id)
                except KeyError:
                    # lg.warn('block %d not found' % (block_id))
                    continue
                block_size = len(outblock[0])
                self.output_buffer_size -= block_size 
                self.bytes_acked += block_size
                relative_time = time.time() - self.creation_time
                last_ack_rtt = relative_time - outblock[1]
                self.rtt_avarage += last_ack_rtt
                self.rtt_acks_counter += 1.0
                if self.rtt_avarage > 1000000 or self.rtt_acks_counter > 1000000:
                    rtt = self.rtt_avarage / self.rtt_acks_counter
                    self.rtt_acks_counter = BLOCKS_PER_ACK * 2
                    self.rtt_avarage = rtt * self.rtt_acks_counter 
                self.consumer.on_sent_raw_data(block_size)
                eof = self.consumer and self.consumer.size == self.bytes_acked
            if acks > 0:
                self.last_ack_received_time = time.time() - self.creation_time
                self.input_acks_counter += 1
                # print 'ack blocks:(%d|%d)' % (acks, len(self.output_blocks.keys())) 
                self.resend()
                return
            # print 'STOP IT NOW!!!!, ZERO ACK!!!! SEEMS FINE.!!!'
            self.stop_resending()
            sum_not_acked_blocks = sum(map(lambda block: len(block[0]), 
                                           self.output_blocks.values()))
            self.output_blocks.clear()
            self.output_buffer_size = 0                
            self.bytes_acked += sum_not_acked_blocks
            relative_time = time.time() - self.creation_time
            self.consumer.on_zero_ack(sum_not_acked_blocks)
            return            

    def write(self, data):
        if self.output_buffer_size + len(data) > MAX_BUFFER_SIZE:
            raise BufferOverflow('buffer size is %d' % self.output_buffer_size)
        # print 'write', len(data)
        outp = cStringIO.StringIO(data)
        while True:
            piece = outp.read(BLOCK_SIZE)
            if not piece:
                break
            self.output_block_id += 1
            self.output_blocks[self.output_block_id] = (piece, -1)
            self.output_buffer_size += len(piece)
        outp.close()
        self.resend()
        
    def send_blocks(self):
        if not self.consumer:
            return False
        relative_time = time.time() - self.creation_time
        current_rate = self.limit_send_bytes_per_sec
        rtt_current = self.rtt_avarage / self.rtt_acks_counter
        if relative_time > 0.0: 
            current_rate = self.bytes_sent / relative_time
        if current_rate > self.limit_send_bytes_per_sec:
            return False
        resend_time_limit = 4 * BLOCKS_PER_ACK * rtt_current
        new_blocks_counter = 0 
        for block_id in self.output_blocks.keys():
            piece, time_sent = self.output_blocks[block_id]
            data_size = len(piece)
            if time_sent >= 0:
                dt = relative_time - time_sent
                if dt > resend_time_limit:
                    self.resend_bytes += data_size
                    # print 're -'s,
                else:
                    # print 'skip', block_id, dt, self.last_ack_rtt 
                    continue
            else:
                pass
                # print 'go', block_id
            time_sent = relative_time
            self.output_blocks[block_id] = (piece, time_sent)
            output = ''.join((
                struct.pack('i', block_id),
                piece))
            # DEBUG
            # import random
            # if random.randint(0, 9) >= 1:
                # 10 % percent lost
                # self.producer.do_send_data(self.stream_id, self.consumer, output)
            self.producer.do_send_data(self.stream_id, self.consumer, output)
            self.bytes_sent += data_size
            self.output_blocks_counter += 1
            new_blocks_counter += 1
        # if new_blocks_counter > 0:
        #     print 'send blocks %d|%d|%d' % (new_blocks_counter, len(self.output_blocks.keys()), self.output_blocks_counter), 
        #     print 'bytes:(%d|%d|%d)' % (self.bytes_acked, self.bytes_sent, self.resend_bytes),  
        #     print 'time:(%s|%s)' % (str(rtt_current)[:8], str(relative_time)[:8]),
        #     print 'rate:(%r)' % current_rate
        return new_blocks_counter > 0

    def send_ack(self):
        if not self.consumer:
            return False
        ack_data = ''.join(map(lambda bid: struct.pack('i', bid), self.blocks_to_ack))
        ack_len = len(ack_data)
        self.producer.do_send_ack(self.stream_id, self.consumer, ack_data)
        self.bytes_in_acks += ack_len 
        # self.output_blocks_acks += list(self.blocks_to_ack)
        self.output_acks_counter += 1
        relative_time = time.time() - self.creation_time
        current_rate = 0.0
        if relative_time > 0.0: 
            current_rate = self.bytes_in / relative_time
        # print 'send ack %d|%d|%d' % (len(self.blocks_to_ack), len(self.output_blocks_acks), self.output_acks_counter), 
        # print 'bytes:(%d|%d)' % (self.bytes_in, self.bytes_in_acks),
        # print 'time:(%r)' % relative_time,
        # print 'rate:(%r)' % current_rate
        self.blocks_to_ack.clear()
        self.last_ack_moment = time.time()
        return ack_len > 0

    def resend(self):
        if not self.consumer:
            print 'stop resending, consumer is None'
            return
        self.resend_counter += 1
        rtt_current = self.rtt_avarage / self.rtt_acks_counter
        rtt_current = max(min(rtt_current, RTT_MAX_LIMIT), RTT_MIN_LIMIT)
        activity = False
        relative_time = time.time() - self.creation_time
        if len(self.blocks_to_ack) > 0:
            if time.time() - self.last_ack_moment > rtt_current:
                activity = activity or self.send_ack()
            if relative_time - self.last_block_received_time > RTT_MAX_LIMIT * 2.0:
                self.producer.on_timeout_receiving(self.stream_id)
        if len(self.output_blocks):        
            activity = activity or self.send_blocks()
            if relative_time - self.last_ack_received_time > RTT_MAX_LIMIT * 4.0:
                self.consumer.on_timeout_sending()
        if activity:
            # print 'resend out:%s acks:%s' % (len(self.output_blocks.keys()), len(self.blocks_to_ack))
            self.resend_inactivity_counter = 0.0
        else:
            self.resend_inactivity_counter += 1.0
        next_resend = rtt_current * self.resend_inactivity_counter * 2.0
        # DEBUG
        if False and self.resend_counter % 10 == 0:
            current_rate_in = 0.0
            current_rate_out = 0.0
            if relative_time > 0.0: 
                current_rate_in = self.bytes_in / relative_time
                current_rate_out = self.bytes_sent / relative_time
            print 'resend (%d:%d)' % (len(self.output_blocks.keys()), len(self.blocks_to_ack)),
            print 'in:(%d|%d|%d)' % (self.input_blocks_counter, self.bytes_in, self.bytes_in_acks),
            print 'out:(%d|%d|%d)' % (self.output_blocks_counter, self.bytes_acked, self.resend_bytes),
            print 'rate:(%d|%d)' % (int(current_rate_in), int(current_rate_out)),  
            print 'time:(%s|%s|%d|%d)' % (str(rtt_current)[:8], str(relative_time)[:6], 
                                          self.resend_counter, self.resend_inactivity_counter)
        # DEBUG
        if self.resend_task is None:
            self.resend_task = reactor.callLater(next_resend, self.resend) 
            return
        if self.resend_task.called:
            self.resend_task = reactor.callLater(next_resend, self.resend)
            return
        if self.resend_task.cancelled:
            self.resend_task = None
            return
            
    def stop_resending(self):
        if self.resend_task:
            if self.resend_task.active():
                self.resend_task.cancel()
                self.resend_task = None
        
#------------------------------------------------------------------------------ 

class BufferOverflow(Exception):
    pass


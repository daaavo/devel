#!/usr/bin/env python
#proxy_router.py
#
# Copyright (C) 2008-2016 Veselin Penev, http://bitdust.io
#
# This file (proxy_router.py) is part of BitDust Software.
#
# BitDust is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# BitDust Software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
# 
# You should have received a copy of the GNU Affero General Public License
# along with BitDust Software.  If not, see <http://www.gnu.org/licenses/>.
#
# Please contact us if you have any questions at bitdust.io@gmail.com


"""
.. module:: proxy_router
.. role:: red

BitDust proxy_router() Automat

.. raw:: html

    <a href="proxy_router.png" target="_blank">
    <img src="proxy_router.png" style="max-width:100%;">
    </a>

EVENTS:
    * :red:`cancel-route`
    * :red:`init`
    * :red:`network-connected`
    * :red:`network-disconnected`
    * :red:`request-route`
    * :red:`request-route-ack-sent`
    * :red:`routed-inbox-packet-received`
    * :red:`routed-outbox-packet-received`
    * :red:`shutdown`
    * :red:`start`
    * :red:`stop`
"""

#------------------------------------------------------------------------------ 

_Debug = True
_DebugLevel = 10

#------------------------------------------------------------------------------ 

import os
import sys
import time
import cStringIO
import json
import pprint

#------------------------------------------------------------------------------ 

try:
    from logs import lg
except:
    dirpath = os.path.dirname(os.path.abspath(sys.argv[0]))
    sys.path.insert(0, os.path.abspath(os.path.join(dirpath, '..')))
    sys.path.insert(0, os.path.abspath(os.path.join(dirpath, '..', '..')))
    from logs import lg

from automats import automat

from lib import nameurl

from main import config

from crypt import key
from crypt import signed
from crypt import encrypted

from userid import identity
from userid import my_id

from contacts import identitycache

from transport import gateway
from transport import callback
from transport import packet_out

from p2p import p2p_service
from p2p import commands
from p2p import network_connector

#------------------------------------------------------------------------------ 

_ProxyRouter = None
_MaxRoutesNumber = 20

#------------------------------------------------------------------------------ 

def A(event=None, arg=None):
    """
    Access method to interact with proxy_router() machine.
    """
    global _ProxyRouter
    if event is None and arg is None:
        return _ProxyRouter
    if _ProxyRouter is None:
        # set automat name and starting state here
        _ProxyRouter = ProxyRouter('proxy_router', 'AT_STARTUP', _DebugLevel, _Debug)
    if event is not None:
        _ProxyRouter.automat(event, arg)
    return _ProxyRouter

#------------------------------------------------------------------------------ 

class ProxyRouter(automat.Automat):
    """
    This class implements all the functionality of the ``proxy_router()`` state machine.
    """

    def init(self):
        """
        Method to initialize additional variables and flags
        at creation phase of proxy_router() machine.
        """
        self.routes = {}
        self.acks = []

    def state_changed(self, oldstate, newstate, event, arg):
        """
        Method to catch the moment when proxy_router() state were changed.
        """

    def state_not_changed(self, curstate, event, arg):
        """
        This method intended to catch the moment when some event was fired in the proxy_router()
        but its state was not changed.
        """

    def A(self, event, arg):
        """
        The state machine code, generated using `visio2python <http://code.google.com/p/visio2python/>`_ tool.
        """
        #---LISTEN---
        if self.state == 'LISTEN':
            if event == 'routed-inbox-packet-received':
                self.doForwardInboxPacket(arg)
                self.doCountIncomingTraffic(arg)
            elif event == 'shutdown':
                self.state = 'CLOSED'
                self.doUnregisterAllRouts(arg)
                self.doDestroyMe(arg)
            elif event == 'request-route' or event == 'cancel-route':
                self.doProcessRequest(arg)
            elif event == 'routed-outbox-packet-received':
                self.doForwardOutboxPacket(arg)
                self.doCountOutgoingTraffic(arg)
            elif event == 'stop' or event == 'network-disconnected':
                self.state = 'STOPPED'
                self.doUnregisterAllRouts(arg)
            elif event == 'request-route-ack-sent':
                self.doSaveRouteProtoHost(arg)
        #---AT_STARTUP---
        elif self.state == 'AT_STARTUP':
            if event == 'init':
                self.state = 'STOPPED'
                self.doInit(arg)
        #---TRANSPORTS?---
        elif self.state == 'TRANSPORTS?':
            if event == 'shutdown':
                self.state = 'CLOSED'
                self.doDestroyMe(arg)
            elif event == 'stop' or event == 'network-disconnected':
                self.state = 'STOPPED'
            elif event == 'network-connected':
                self.state = 'LISTEN'
        #---STOPPED---
        elif self.state == 'STOPPED':
            if event == 'start':
                self.state = 'TRANSPORTS?'
            elif event == 'shutdown':
                self.state = 'CLOSED'
                self.doDestroyMe(arg)
        #---CLOSED---
        elif self.state == 'CLOSED':
            pass
        return None

    def doInit(self, arg):
        """
        Action method.
        """
#         self.starting_transports = []
        self._load_routes()
        network_connector.A().addStateChangedCallback(self._on_network_connector_state_changed)
        # gateway.add_transport_state_changed_callback(self._on_transport_state_changed)
        callback.insert_inbox_callback(0, self._on_inbox_packet_received)
        callback.add_finish_file_sending_callback(self._on_finish_file_sending)

    def doProcessRequest(self, arg):
        """
        Action method.
        """
        global _MaxRoutesNumber
        request, _ = arg
        target = request.CreatorID
        if request.Command == commands.RequestService():
            if len(self.routes) >= _MaxRoutesNumber:
                if _Debug:
                    lg.out(_DebugLevel, 'proxy_server.doProcessRequest RequestService rejected: too many routes')
                    lg.out(_DebugLevel, '    %s' % pprint.pformat(self.routes))
                p2p_service.SendAck(request, 'rejected', wide=True)
            else:
                try:
                    service_info = request.Payload
                    idsrc = service_info.lstrip('service_proxy_server').strip()
                    cached_id = identity.identity(xmlsrc=idsrc)
                except:
                    lg.out(_DebugLevel, 'payload: [%s]' % request.Payload)
                    lg.exc()
                    return
                oldnew = ''
                if target not in self.routes.keys():
                    # accept new route
                    oldnew = 'NEW'
                    self.routes[target] = {}
                    # cached_id = identitycache.FromCache(target)
                    # idsrc = cached_id.serialize()
                else:
                    oldnew = 'OLD'
#                    try:
#                        idsrc = self.routes[target]['identity']
#                        cached_id = identity.identity(xmlsrc=idsrc)
#                    except:
#                        lg.exc()
#                        cached_id = identitycache.FromCache(target)
#                        idsrc = cached_id.serialize()
                    # lg.warn('route with %s already exist' % target)
                if not self._is_my_contacts_present_in_identity(cached_id): 
                    identitycache.OverrideIdentity(target, idsrc)
                else:
                    if _Debug:
                        lg.out(_DebugLevel, '        skip overriding %s' % target)
                self.routes[target]['time'] = time.time()
                self.routes[target]['identity'] = idsrc
                self.routes[target]['publickey'] = cached_id.publickey
                self.routes[target]['contacts'] = cached_id.getContactsAsTuples()
                self.routes[target]['address'] = []
                self._write_route(target)
                self.acks.append(
                    p2p_service.SendAck(
                        request, 
                        'accepted', 
                        wide=True, 
                        packetid=request.PacketID)) 
                if _Debug:
                    lg.out(_DebugLevel, 'proxy_server.doProcessRequest !!!!!!! ACCEPTED %s ROUTE for %s' % (oldnew, target))
        elif request.Command == commands.CancelService():
            if self.routes.has_key(target):
                # cancel existing route
                self._remove_route(target)
                self.routes.pop(target)
                identitycache.StopOverridingIdentity(target)
                p2p_service.SendAck(request, 'accepted', wide=True)
                if _Debug:
                    lg.out(_DebugLevel, 'proxy_server.doProcessRequest !!!!!!! CANCELLED ROUTE for %s' % target)
            else:
                p2p_service.SendAck(request, 'rejected', wide=True)
                if _Debug:
                    lg.out(_DebugLevel, 'proxy_server.doProcessRequest CancelService rejected : %s is not found in routes' % target)
                    lg.out(_DebugLevel, '    %s' % pprint.pformat(self.routes))
        else:
            p2p_service.SendFail(request, 'wrong command or payload') # , wide=True)

    def doUnregisterAllRouts(self, arg):
        """
        Action method.
        """
        for idurl in self.routes.keys():
            identitycache.StopOverridingIdentity(idurl)
        self.routes.clear()
        self._clear_routes()

    def doForwardOutboxPacket(self, arg):
        """
        Action method.
        """
        # decrypt with my key and send to outside world
        newpacket, _ = arg
        block = encrypted.Unserialize(newpacket.Payload)
        if block is None:
            lg.out(2, 'proxy_router.doForwardOutboxPacket ERROR reading data from %s' % newpacket.RemoteID)
            return
        try:
            session_key = key.DecryptLocalPK(block.EncryptedSessionKey)
            padded_data = key.DecryptWithSessionKey(session_key, block.EncryptedData)
            inpt = cStringIO.StringIO(padded_data[:int(block.Length)])
            sender_idurl = inpt.readline().rstrip('\n')
            receiver_idurl = inpt.readline().rstrip('\n')
            wide = inpt.readline().rstrip('\n')
            wide = wide == 'wide'
        except:
            lg.out(2, 'proxy_router.doForwardOutboxPacket ERROR reading data from %s' % newpacket.RemoteID)
            lg.out(2, '\n' + padded_data)
            lg.exc()
            try:
                inpt.close()
            except:
                pass
            return
        route = self.routes.get(sender_idurl, None)
        if not route:
            inpt.close()
            lg.warn('route with %s not found' % (sender_idurl))
            p2p_service.SendFail(newpacket, 'route not exist', remote_idurl=sender_idurl)
            return 
        data = inpt.read()
        inpt.close()
        routed_packet = signed.Unserialize(data)
        gateway.outbox(routed_packet, wide=wide)
        if _Debug:
            lg.out(_DebugLevel, 'proxy_router.doForwardOutboxPacket %d bytes from %s routed to %s : %s' % (
                len(data), nameurl.GetName(sender_idurl), nameurl.GetName(receiver_idurl), str(routed_packet)))
        del block
        del data
        del padded_data
        del route
        del inpt
        del session_key
        del routed_packet

    def doForwardInboxPacket(self, arg):
        """
        Action method.
        """
        # encrypt with proxy_receiver()'s key and sent to man behind my proxy
        newpacket, _ = arg
        receiver_idurl = newpacket.RemoteID
        route_info = self.routes.get(receiver_idurl, None)
        if not route_info:
            lg.warn('route with %s not exist' % receiver_idurl)
            return
        hosts = route_info['address']
        if len(hosts) == 0:
            lg.warn('route with %s do not have actual info about his host, use his identity contacts' % receiver_idurl)
            hosts = route_info['contacts'] 
        if len(hosts) == 0:
            lg.warn('has no known contacts for route with %s' % receiver_idurl)
            return
        receiver_proto, receiver_host = hosts[0]
        publickey = route_info['publickey']
        src = ''
        src += newpacket.Serialize()
        block = encrypted.Block(
            my_id.getLocalID(),
            'routed incoming data',
            0,
            key.NewSessionKey(),
            key.SessionKeyType(),
            True,
            src,
            EncryptFunc=lambda inp: key.EncryptStringPK(publickey, inp))
        routed_packet = signed.Packet(
            commands.Data(), 
            newpacket.OwnerID,
            my_id.getLocalID(), 
            # 'routed_in_'+newpacket.PacketID, 
            newpacket.PacketID, 
            block.Serialize(), 
            receiver_idurl)
        packet_out.create(
            newpacket, 
            wide=False,
            callbacks={},
            route={
                'packet': routed_packet,
                'proto': receiver_proto,
                'host': receiver_host,
                'remoteid': receiver_idurl,
                'description': ('Routed_%s' % nameurl.GetName(receiver_idurl))})
#        fileno, filename = tmpfile.make('proxy-in')
#        packetdata = routed_packet.Serialize()
#        os.write(fileno, packetdata)
#        os.close(fileno)
#        gateway.send_file(
#            receiver_idurl, 
#            receiver_proto, 
#            receiver_host, filename,
#            'Routed packet for %s' % receiver_idurl)
        if _Debug:
            lg.out(_DebugLevel-8, '>>> ROUTED-IN >>> %s' % str(routed_packet))
            lg.out(_DebugLevel-8, '                   sent on %s://%s with %d bytes' % (
                receiver_proto, receiver_host, len(src)))
        # gateway.outbox(routed_packet)
#        if _Debug:
#            lg.out(_DebugLevel, 'proxy_router.doForwardInboxPacket %d bytes from %s sent to %s' % (
#                len(src),  nameurl.GetName(newpacket.CreatorID), nameurl.GetName(receiver_idurl)))
        del src
        del block
        del newpacket
        # del receiver_ident_obj
        del routed_packet
                
    def doCountOutgoingTraffic(self, arg):
        """
        Action method.
        """

    def doCountIncomingTraffic(self, arg):
        """
        Action method.
        """

    def doSaveRouteProtoHost(self, arg):
        """
        Action method.
        """
        idurl, _, item, _, _, _ = arg
        self.routes[idurl]['address'].append((item.proto, item.host))
        self._write_route(idurl)
        if _Debug:
            lg.out(_DebugLevel, 'proxy_router.doSaveRouteProtoHost : active address %s://%s added for %s' % (
                item.proto, item.host, nameurl.GetName(idurl)))

    def doDestroyMe(self, arg):
        """
        Remove all references to the state machine object to destroy it.
        """
        # gateway.remove_transport_state_changed_callback(self._on_transport_state_changed)
        network_connector.A().removeStateChangedCallback(self._on_network_connector_state_changed)
        callback.remove_inbox_callback(self._on_inbox_packet_received)
        callback.remove_finish_file_sending_callback(self._on_finish_file_sending)
        automat.objects().pop(self.index)
        global _ProxyRouter
        del _ProxyRouter
        _ProxyRouter = None

    def _on_inbox_packet_received(self, newpacket, info, status, error_message):
        if newpacket.RemoteID == my_id.getLocalID():
            if newpacket.Command == commands.Data() and newpacket.CreatorID in self.routes.keys():
                # sent by proxy_sender() from node A : a man behind proxy_router()
                # addressed to some third node - need to route
                self.automat('routed-outbox-packet-received', (newpacket, info))
                return True
            if newpacket.Command == commands.Identity() and \
                newpacket.CreatorID in self.routes.keys() and \
                newpacket.CreatorID == newpacket.OwnerID:
                # this is a "propagate" packet from node A addressed to this proxy
                # mark that packet as handled and send Ack
                # otherwise it will be wrongly handled in p2p_service
                p2p_service.SendAck(newpacket, wide=True)
                if _Debug:
                    lg.out(_DebugLevel, 'proxy_router._on_inbox_packet_received packet from known node: %s' % newpacket.OwnerID)
                return True
            return False
        if newpacket.RemoteID in self.routes.keys():
            # sent by node B : a man from outside world
            # addressed to a man behind this proxy - need to route
            self.automat('routed-inbox-packet-received', (newpacket, info))
            return True
        return False             

    def _on_network_connector_state_changed(self, oldstate, newstate, event, arg):
        if oldstate != 'CONNECTED' and newstate == 'CONNECTED':
            self.automat('network-connected')
        if oldstate != 'DISCONNECTED' and newstate == 'DISCONNECTED':
            self.automat('network-disconnected')

    def _on_finish_file_sending(self, pkt_out, item, status, size, error_message):
        if status != 'finished':
            return False
        try:
            Command = pkt_out.outpacket.Command
            RemoteID = pkt_out.outpacket.RemoteID
            PacketID = pkt_out.outpacket.PacketID
        except:
            lg.exc()
            return False
        if Command != commands.Ack():
            return False
        if not RemoteID in self.routes.keys():
            return False
        for ack in self.acks:
            if PacketID == ack.PacketID:
                self.automat('request-route-ack-sent', (RemoteID, pkt_out, item, status, size, error_message))
        return True
        
    def _is_my_contacts_present_in_identity(self, ident):
        for my_contact in my_id.getLocalIdentity().getContacts():
            if ident.getContactIndex(contact=my_contact) >= 0:
                if _Debug:
                    lg.out(_DebugLevel, '        found %s in identity : %s' % (
                        my_contact, ident.getIDURL()))
                return True
        return False
                
    def _load_routes(self):
        src = config.conf().getData('services/proxy-server/current-routes')
        if src is None:
            lg.warn('setting [services/proxy-server/current-routes] not exist')
            return
        try:
            dct = json.loads(src)
        except:
            dct = {}
        for k,v in dct.items():
            self.routes[k] = v
            ident = identity.identity(xmlsrc=v['identity'])
            if not self._is_my_contacts_present_in_identity(ident): 
                identitycache.OverrideIdentity(k, v['identity'])
            else:
                if _Debug:
                    lg.out(_DebugLevel, '        skip overriding %s' % k)
        if _Debug:
            lg.out(_DebugLevel, 'proxy_router._load_routes %d routes total' % len(self.routes))

    def _clear_routes(self):
        config.conf().setData('services/proxy-server/current-routes', '{}')
        if _Debug:
            lg.out(_DebugLevel, 'proxy_router._clear_routes') 
    
    def _write_route(self, target):
        src = config.conf().getData('services/proxy-server/current-routes')
        try:
            dct = json.loads(src)
        except:
            dct = {}
        dct[target] = self.routes[target]
        newsrc = pprint.pformat(json.dumps(dct, indent=0))
        config.conf().setData('services/proxy-server/current-routes', newsrc)
        if _Debug:
            lg.out(_DebugLevel, 'proxy_router._write_route %d bytes wrote' % len(newsrc)) 
    
    def _remove_route(self, target):
        src = config.conf().getData('services/proxy-server/current-routes')
        try:
            dct = json.loads(src)
        except:
            dct = {}
        if target in dct:
            dct.pop(target)
        newsrc = json.dumps(dct)
        config.conf().setData('services/proxy-server/current-routes', newsrc)
        if _Debug:
            lg.out(_DebugLevel, 'proxy_router._remove_route %d bytes wrote' % len(newsrc)) 

#------------------------------------------------------------------------------ 

def main():
    from twisted.internet import reactor
    reactor.callWhenRunning(A, 'init')
    reactor.run()

if __name__ == "__main__":
    main()


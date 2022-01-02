#!/usr/bin/env python
# initializer.py
#
# Copyright (C) 2008 Veselin Penev, https://bitdust.io
#
# This file (initializer.py) is part of BitDust Software.
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
#
#
#
#
#

"""
.. module:: initializer.

.. raw:: html

    <a href="https://bitdust.io/automats/initializer/initializer.png" target="_blank">
    <img src="https://bitdust.io/automats/initializer/initializer.png" style="max-width:100%;">
    </a>

This Automat is the "entry point" to run all other state machines.
It manages the process of initialization of the whole program.

It also checks whether the program is installed and switch to run another "installation" code if needed.

The ``initializer()`` machine is doing several operations:

    * start low-level modules and init local data, see ``initializer._init_local()``
    * starts the network communications by running core method ``initializer.doInitServices()``
    * other modules is started after all other more important things
    * machine can switch to "install" wizard if Private Key or local identity file is not fine
    * it will finally switch to "READY" state to indicate the whole status of the application
    * during shutting down it will wait for ``shutdowner()`` automat to do its work completely
    * once ``shutdowner()`` become "FINISHED" - the state machine changes its state to "EXIT" and is destroyed


EVENTS:
    * :red:`init-interfaces-done`
    * :red:`init-local-done`
    * :red:`init-modules-done`
    * :red:`init-services-done`
    * :red:`installer.state`
    * :red:`run`
    * :red:`run-cmd-line-recover`
    * :red:`run-cmd-line-register`
    * :red:`shutdowner.state`
"""

from __future__ import absolute_import

#------------------------------------------------------------------------------

_Debug = True
_DebugLevel = 6

#------------------------------------------------------------------------------

import os
import sys

try:
    from twisted.internet import reactor  # @UnresolvedImport
except:
    sys.exit('Error initializing twisted.internet.reactor in initializer.py')

#------------------------------------------------------------------------------

from logs import lg

from system import bpio
from system import local_fs

from crypt import cipher

from main import settings
from main import events

from automats import automat

from services import driver

#------------------------------------------------------------------------------

_Initializer = None

#------------------------------------------------------------------------------


def A(event=None, *args, **kwargs):
    """
    Access method to interact with the state machine.
    """
    global _Initializer
    if _Initializer is None:
        _Initializer = Initializer('initializer', 'AT_STARTUP', 2, True)
    if event is not None:
        if kwargs.get('use_reactor', True):
            _Initializer.automat(event, *args, **kwargs)
        else:
            _Initializer.event(event, *args, **kwargs)
    return _Initializer


def Destroy():
    """
    Destroy initializer() automat and remove its instance from memory.
    """
    global _Initializer
    if _Initializer is None:
        return
    _Initializer.destroy()
    del _Initializer
    _Initializer = None


class Initializer(automat.Automat):
    """
    A class to execute start up operations to launch BitDust software.
    """

    fast = True

    def init(self):
        self.flagCmdLine = False
        self.flagGUI = False
        self.is_installed = None

    def A(self, event, *args, **kwargs):
        from main import installer
        from main import shutdowner
        #---AT_STARTUP---
        if self.state == 'AT_STARTUP':
            if event == 'run':
                self.state = 'LOCAL'
                shutdowner.A('init')
                self.doInitLocal(*args, **kwargs)
                self.flagCmdLine=False
            elif event == 'run-cmd-line-register':
                self.state = 'INSTALL'
                shutdowner.A('init')
                self.flagCmdLine=True
                installer.A('register-cmd-line', *args, **kwargs)
                shutdowner.A('ready')
            elif event == 'run-cmd-line-recover':
                self.state = 'INSTALL'
                shutdowner.A('init')
                self.flagCmdLine=True
                installer.A('recover-cmd-line', *args, **kwargs)
                shutdowner.A('ready')
        #---LOCAL---
        elif self.state == 'LOCAL':
            if event == 'init-local-done' and not self.isInstalled(*args, **kwargs) and self.isGUIPossible(*args, **kwargs):
                self.state = 'INSTALL'
                installer.A('init')
                shutdowner.A('ready')
                self.doInitInterfaces(*args, **kwargs)
                self.doShowGUI(*args, **kwargs)
                self.doUpdate(*args, **kwargs)
            elif ( event == 'shutdowner.state' and args[0] == 'FINISHED' ):
                self.state = 'STOPPING'
                self.doDestroyMe(*args, **kwargs)
            elif event == 'init-local-done' and ( ( not self.isInstalled(*args, **kwargs) and not self.isGUIPossible(*args, **kwargs) ) or self.isInstalled(*args, **kwargs) ):
                self.state = 'INTERFACES'
                shutdowner.A('ready')
                self.doInitInterfaces(*args, **kwargs)
        #---MODULES---
        elif self.state == 'MODULES':
            if event == 'init-modules-done':
                self.state = 'READY'
                self.doUpdate(*args, **kwargs)
                self.doShowGUI(*args, **kwargs)
            elif ( event == 'shutdowner.state' and args[0] == 'FINISHED' ):
                self.state = 'EXIT'
                self.doDestroyMe(*args, **kwargs)
        #---INSTALL---
        elif self.state == 'INSTALL':
            if not self.flagCmdLine and ( event == 'installer.state' and args[0] == 'DONE' ):
                self.state = 'STOPPING'
                shutdowner.A('stop', "restartnshow")
            elif self.flagCmdLine and ( event == 'installer.state' and args[0] == 'DONE' ):
                self.state = 'STOPPING'
                shutdowner.A('stop', "exit")
            elif ( event == 'shutdowner.state' and args[0] == 'FINISHED' ):
                self.state = 'EXIT'
                self.doDestroyMe(*args, **kwargs)
        #---READY---
        elif self.state == 'READY':
            if ( event == 'shutdowner.state' and args[0] == 'FINISHED' ):
                self.state = 'EXIT'
                self.doDestroyMe(*args, **kwargs)
        #---STOPPING---
        elif self.state == 'STOPPING':
            if ( event == 'shutdowner.state' and args[0] == 'FINISHED' ):
                self.state = 'EXIT'
                self.doUpdate(*args, **kwargs)
                self.doDestroyMe(*args, **kwargs)
        #---EXIT---
        elif self.state == 'EXIT':
            pass
        #---SERVICES---
        elif self.state == 'SERVICES':
            if event == 'init-services-done':
                self.state = 'MODULES'
                self.doInitModules(*args, **kwargs)
                shutdowner.A('ready')
            elif ( event == 'shutdowner.state' and args[0] == 'FINISHED' ):
                self.state = 'EXIT'
                self.doDestroyMe(*args, **kwargs)
        #---INTERFACES---
        elif self.state == 'INTERFACES':
            if event == 'init-interfaces-done':
                self.state = 'SERVICES'
                self.doInitServices(*args, **kwargs)
            elif ( event == 'shutdowner.state' and args[0] == 'FINISHED' ):
                self.state = 'EXIT'
                self.doDestroyMe(*args, **kwargs)
        return None

    def isInstalled(self, *args, **kwargs):
        if self.is_installed is None:
            self.is_installed = self._check_install()
        return self.is_installed

    def isGUIPossible(self, *args, **kwargs):
        return bpio.isGUIpossible()

    def doUpdate(self, *args, **kwargs):
        from main import control
        control.request_update()

    def doInitLocal(self, *args, **kwargs):
        """
        """
        self.flagGUI = args[0].strip() == 'show'
        if _Debug:
            lg.out(_DebugLevel, 'initializer.doInitLocal flagGUI=%s' % self.flagGUI)
        self._init_local()
        if bpio.Android():
            self.automat('init-local-done')
        else:
            reactor.callWhenRunning(self.automat, 'init-local-done')  # @UndefinedVariable

    def doInitServices(self, *args, **kwargs):
        """
        Action method.
        """
        if bpio.Android():
            lg.close_intercepted_log_file()
            lg.open_intercepted_log_file('/storage/emulated/0/.bitdust/logs/android.log', mode='a')
            if _Debug:
                lg.dbg(_DebugLevel, 'log file "android.log" re-opened')
        if _Debug:
            lg.out(_DebugLevel, 'initializer.doInitServices')
        driver.init()
        d = driver.start()
        d.addBoth(lambda x: self.automat('init-services-done'))

    def doInitInterfaces(self, *args, **kwargs):
        if _Debug:
            lg.out(_DebugLevel, 'initializer.doInitInterfaces')
        # if settings.enableFTPServer():
        #     try:
        #         from interface import ftp_server
        #         ftp_server.init()
        #     except:
        #         lg.exc()
        if settings.enableAPIAuthSecret():
            current_secret = local_fs.ReadTextFile(settings.APISecretFile())
            if not current_secret:
                new_secret = cipher.generate_secret_text(10)
                local_fs.WriteTextFile(settings.APISecretFile(), new_secret)
                lg.info('generated new API auth secret text and stored in %r' % settings.APISecretFile())
        if settings.enableRESTHTTPServer():
            try:
                from interface import api_rest_http_server
                api_rest_http_server.init(port=settings.getRESTHTTPServerPort())
            except:
                lg.exc()
        if settings.enableWebSocketServer():
            try:
                from interface import api_web_socket
                api_web_socket.init(port=settings.getWebSocketServerPort())
            except:
                lg.exc()
        reactor.callLater(0, self.automat, 'init-interfaces-done')  # @UndefinedVariable

    def doInitModules(self, *args, **kwargs):
        if _Debug:
            lg.out(_DebugLevel, 'initializer.doInitModules')
        self._init_modules()
        reactor.callLater(0, self.automat, 'init-modules-done')  # @UndefinedVariable

    def doShowGUI(self, *args, **kwargs):
        if _Debug:
            lg.out(_DebugLevel, 'initializer.doShowGUI')
        from main import control
        control.init()
        try:
            from system.tray_icon import USE_TRAY_ICON
        except:
            USE_TRAY_ICON = False
            lg.exc()
        if USE_TRAY_ICON:
            from system import tray_icon
            tray_icon.SetControlFunc(self._on_tray_icon_command)
        # TODO: raise up electron window ?

    def doDestroyMe(self, *args, **kwargs):
        global _Initializer
        try:
            from system.tray_icon import USE_TRAY_ICON
        except:
            USE_TRAY_ICON = False
        if USE_TRAY_ICON:
            from system import tray_icon
            tray_icon.SetControlFunc(None)
        del _Initializer
        _Initializer = None
        self.destroy()

    #------------------------------------------------------------------------------

    def _check_install(self):
        """
        Return True if Private Key and local identity files exists and both is
        valid.
        """
        if _Debug:
            lg.out(_DebugLevel, 'initializer._check_install')
        from userid import identity
        from crypt import key
        keyfilename = settings.KeyFileName()
        keyfilenamelocation = settings.KeyFileNameLocation()
        if os.path.exists(keyfilenamelocation):
            keyfilename = bpio.ReadTextFile(keyfilenamelocation)
            if not os.path.exists(keyfilename):
                keyfilename = settings.KeyFileName()
        idfilename = settings.LocalIdentityFilename()
        if not os.path.exists(keyfilename) or not os.path.exists(idfilename):
            if _Debug:
                lg.out(_DebugLevel, 'initializer._check_install local key or local id not exists')
            return False
        current_key = bpio.ReadTextFile(keyfilename)
        current_id = bpio.ReadTextFile(idfilename)
        if not current_id:
            if _Debug:
                lg.out(_DebugLevel, 'initializer._check_install local identity is empty ')
            return False
        if not current_key:
            if _Debug:
                lg.out(_DebugLevel, 'initializer._check_install private key is empty ')
            return False
        try:
            key.InitMyKey()
        except:
            if _Debug:
                lg.out(_DebugLevel, 'initializer._check_install fail loading private key ')
            return False
        try:
            ident = identity.identity(xmlsrc=current_id)
        except:
            if _Debug:
                lg.out(_DebugLevel, 'initializer._check_install fail init local identity ')
            return False
        if not ident.isCorrect():
            lg.err('local identity is not correct !!!')
            return False
        try:
            res = ident.Valid()
        except:
            if _Debug:
                lg.out(_DebugLevel, 'failed to validate local identity')
            return False
        if not res:
            lg.err('local identity is not valid !!!')
            return False
        if _Debug:
            lg.out(_DebugLevel, 'initializer._check_install SUCCESS!!!')
        return True

    def _init_local(self):
        from p2p import commands
        from lib import net_misc
        from lib import misc
        from system import tmpfile
        from system import run_upnpc
        from raid import eccmap
        from contacts import identitydb
        from crypt import my_keys
        from userid import id_url
        from userid import my_id
        id_url.init()
        identitydb.init()
        my_id.init()
        if settings.enableWebStream():
            try:
                from logs import weblog
                weblog.init(settings.getWebStreamPort())
            except:
                lg.exc()
        if settings.enableWebTraffic():
            try:
                from logs import webtraffic
                webtraffic.init(port=settings.getWebTrafficPort())
            except:
                lg.exc()
        misc.init()
        commands.init()
        tmpfile.init(settings.getTempDir())
        net_misc.init()
        settings.update_proxy_settings()
        run_upnpc.init()
        eccmap.init()
        my_keys.init()
        # if sys.argv.count('--twisted'):
        #     from twisted.python import log as twisted_log
        #     twisted_log.startLogging(MyTwistedOutputLog(), setStdout=0)
            # import twisted.python.failure as twisted_failure
            # twisted_failure.startDebugMode()
            # twisted_log.defaultObserver.stop()
        # if settings.getDebugLevel() > 10:
        #     defer.setDebugging(True)
        if settings.enableMemoryProfile():
            try:
                from guppy import hpy  # @UnresolvedImport
                hp = hpy()
                hp.setrelheap()
                if _Debug:
                    lg.out(_DebugLevel, 'hp.heap():\n'+str(hp.heap()))
                    lg.out(_DebugLevel, 'hp.heap().byrcs:\n'+str(hp.heap().byrcs))
                    lg.out(_DebugLevel, 'hp.heap().byvia:\n'+str(hp.heap().byvia))
            except:
                if _Debug:
                    lg.out(_DebugLevel, "guppy package is not installed")
        if _Debug:
            lg.dbg(_DebugLevel, 'all local modules are initialized, ready to start the engine')

    def _on_software_code_updated(self, evt):
        if _Debug:
            lg.out(_DebugLevel, 'initializer._on_software_code_updated will RESTART BitDust now! "source-code-fetched" event received')
        if False:
            # TODO: add checks to prevent restart if any important jobs running at the moment
            return
        if False:
            # TODO: add an option to the settings
            return
        from main import shutdowner
        shutdowner.A('stop', 'restart')

    def _init_modules(self):
        """
        Finish initialization part, run delayed methods.
        """
        if _Debug:
            lg.out(_DebugLevel, "initializer._init_modules")
        from updates import git_proc
        git_proc.init()
        events.add_subscriber(self._on_software_code_updated, 'source-code-fetched')

    def _on_tray_icon_command(self, cmd):
        if _Debug:
            lg.out(_DebugLevel, "initializer._on_tray_icon_command : [%s]" % cmd)
        try:
            from main import shutdowner
            if cmd == 'exit':
                shutdowner.A('stop', 'exit')

            elif cmd == 'restart':
                shutdowner.A('stop', 'restart')

            elif cmd == 'reconnect':
                from p2p import network_connector
                if driver.is_on('service_network'):
                    network_connector.A('reconnect')

            elif cmd == 'show':
                # TODO: raise up electron window ?
                pass

            elif cmd == 'sync':
                try:
                    from updates import git_proc
                    from system import tray_icon

                    def _sync_callback(result):
                        if result == 'error':
                            tray_icon.draw_icon('error')
                            reactor.callLater(5, tray_icon.restore_icon)  # @UndefinedVariable
                            return
                        elif result == 'source-code-fetched':
                            tray_icon.draw_icon('updated')
                            reactor.callLater(5, tray_icon.restore_icon)  # @UndefinedVariable
                            return
                        tray_icon.restore_icon()

                    tray_icon.draw_icon('sync')
                    git_proc.sync(_sync_callback, update_method='reset')
                except:
                    lg.exc()

            elif cmd == 'hide':
                pass

            elif cmd == 'toolbar':
                pass

            else:
                lg.warn('wrong command: ' + str(cmd))
        except:
            lg.exc()

#------------------------------------------------------------------------------


class MyTwistedOutputLog:
    softspace = 0

    def read(self):
        pass

    def write(self, s):
        if _Debug:
            lg.out(_DebugLevel, 'TWISTED: ' + s.strip())

    def flush(self):
        pass

    def close(self):
        pass

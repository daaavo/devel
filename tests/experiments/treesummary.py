#!/usr/bin/env python
# treesummary.py
#
# Copyright (C) 2008 Veselin Penev, https://bitdust.io
#
# This file (treesummary.py) is part of BitDust Software.
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
from __future__ import absolute_import, print_function

import os
import os.path as _p
import sys

sys.path.insert(0, _p.abspath(_p.join(_p.dirname(_p.abspath(sys.argv[0])), "..")))
from lib import nameurl
from main import settings
from p2p import p2p_service

custdir = settings.getCustomersFilesDir()
ownerdir = os.path.join(custdir, nameurl.UrlFilename("http://megafaq.ru/e_vps1004.xml"))
plaintext = p2p_service.TreeSummary(ownerdir)
print(plaintext)

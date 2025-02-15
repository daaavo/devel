#!/usr/bin/env python
# test_supplieridrotate.py
#
# Copyright (C) 2008 Veselin Penev  https://bitdust.io
#
# This file (test_supplieridrotate.py) is part of BitDust Software.
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
SCENARIO 9: ID server id-dead is dead and few nodes has rotated identities

SCENARIO 13: one of the suppliers of customer-1 has IDURL rotated

"""

import os
import pytest

from testsupport import set_active_scenario  # @UnresolvedImport

import keywords as kw  # @UnresolvedImport
import scenarios


def test_supplieridrotate():
    if os.environ.get('RUN_TESTS', '1') == '0':
        return pytest.skip()  # @UndefinedVariable

    prepare()

    #--- SCENARIO 13 begin: supplier of customer-1 has IDURL rotated
    old_customer_1_info_s13 = scenarios.scenario13_begin()

    #--- SCENARIO 9: ID server id-dead is dead
    scenarios.scenario9(target_nodes=['supplier-rotated', ])

    #--- SCENARIO 13 end: supplier of customer-1 has IDURL rotated
    scenarios.scenario13_end(old_customer_1_info_s13)

#------------------------------------------------------------------------------

def prepare():
    set_active_scenario('PREPARE')
    kw.wait_suppliers_connected(scenarios.CUSTOMERS_IDS_1, expected_min_suppliers=2, expected_max_suppliers=2)
    kw.wait_service_state(scenarios.SUPPLIERS_IDS_12 + ['supplier-rotated', ], 'service_supplier', 'ON')
    kw.wait_service_state(scenarios.CUSTOMERS_IDS_1, 'service_customer', 'ON')
    kw.wait_service_state(scenarios.CUSTOMERS_IDS_1, 'service_shared_data', 'ON')
    # kw.wait_service_state(scenarios.CUSTOMERS_IDS_1, 'service_personal_messages', 'ON')
    kw.wait_service_state(scenarios.CUSTOMERS_IDS_1, 'service_private_groups', 'ON')
    kw.wait_service_state(scenarios.CUSTOMERS_IDS_1, 'service_message_history', 'ON')
    kw.wait_packets_finished(scenarios.CUSTOMERS_IDS_1 + scenarios.SUPPLIERS_IDS_12 + ['supplier-rotated', ])

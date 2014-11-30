########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import re
import time
import socket

from elasticsearch import Elasticsearch
from neutronclient.common.exceptions import NeutronClientException

from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework.handlers.openstack import OpenstackHandler

ELASTICSEARCH_PORT = 9200

TIMESTAMP_PATTERN = '\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}.\d{3}'

DEFAULT_EXECUTE_TIMEOUT = 1800


class ElasticsearchTimestampFormatTest(TestCase):

    """
    CFY-54
    this test checks Elasticsearch Timestamp Format.
    it creates events by uploading a blueprint and creating deployment.
    after creating events the test connects to Elasticsearch and compares
    Timestamp Format of the events to a regular expression.

    This test requires access to the management on port 9200 (elastic search",
    The rule is added by _create_elasticsearch_rule
    """
    def _create_elasticsearch_rule(self):
        os_handler = OpenstackHandler(self.env)
        neutron_client = os_handler.openstack_clients()[1]
        sgr = {
            'direction': 'ingress',
            'ethertype': 'IPv4',
            'port_range_max': str(ELASTICSEARCH_PORT),
            'port_range_min': str(ELASTICSEARCH_PORT),
            'protocol': 'tcp',
            'remote_group_id': None,
            'remote_ip_prefix': '0.0.0.0/0',
            }

        mng_sec_grp_name = self.env.management_security_group

        mng_sec_grp = neutron_client. \
            list_security_groups(name=mng_sec_grp_name)['security_groups'][0]

        sg_id = mng_sec_grp['id']
        sgr['security_group_id'] = sg_id
        try:
            self.elasticsearch_rule = neutron_client.\
                create_security_group_rule(
                    {'security_group_rule': sgr})['security_group_rule']['id']
            if not self._wait_for_open_port(self.env.management_ip,
                                            ELASTICSEARCH_PORT,
                                            60):
                raise Exception('Couldn\'t open elasticsearch port')

        except NeutronClientException as e:
            self.elasticsearch_rule = None
            self.logger.warning("Got NeutronClientException({0}). Resuming"
                                .format(e))
            pass

    def setUp(self):
        super(ElasticsearchTimestampFormatTest, self).setUp()
        self._create_elasticsearch_rule()

    def _delete_elasticsearch_rule(self):
        if self.elasticsearch_rule is not None:
            os_handler = OpenstackHandler(self.env)
            neutron_client = os_handler.openstack_clients()[1]
            neutron_client.delete_security_group_rule(self.elasticsearch_rule)

    def tearDown(self):
        self.execute_uninstall()
        self._delete_elasticsearch_rule()
        super(ElasticsearchTimestampFormatTest, self).tearDown()

    def _check_port(self, ip, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((ip, port))
        return result == 0

    def _wait_for_open_port(self, ip, port, timeout):
        timeout = time.time() + timeout
        is_open = False
        while not is_open:
            if time.time() > timeout:
                break
            is_open = self._check_port(ip, port)
        return is_open

    def test_events_timestamp_format(self):
        self.blueprint_path = self.copy_blueprint('mocks')
        self.blueprint_yaml = self.blueprint_path / 'empty-bp.yaml'

        deployment_id = self.test_id
        self.upload_deploy_and_execute_install(deployment_id=deployment_id)

        #  connect to Elastic search

        es = Elasticsearch(self.env.management_ip +
                           ':' + str(ELASTICSEARCH_PORT))

        res = es.search(index="cloudify_events",
                        body={"query": {"match":
                                        {"deployment_id": deployment_id}}})
        self.logger.info("Got %d Hits:" % res['hits']['total'])
        #  check if events were created
        self.assertNotEqual(0, res['hits']['total'],
                            'There are no events in for '
                            'deployment ' + deployment_id)

        #  loop over all the events and compare timestamp to regular expression
        for hit in res['hits']['hits']:
            if not (re.match(TIMESTAMP_PATTERN, hit["_source"]['timestamp'])):
                self.fail('Got {0}. Does not match format '
                          'YYYY-MM-DD HH:MM:SS.***'
                          .format(hit["_source"]['timestamp']))

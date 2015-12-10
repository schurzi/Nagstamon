# encoding: utf-8

# Nagstamon - Nagios status monitor for your desktop
# Copyright (C) 2008-2014 Henri Wahl <h.wahl@ifw-dresden.de> et al.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA

import sys
import urllib
import copy
import pprint
import json

from datetime import datetime, timedelta
from ast import literal_eval

from Nagstamon import Actions
from Nagstamon.Objects import *
from Nagstamon.Server.Generic import GenericServer


class OpsviewService(GenericService):
    """
    add Opsview specific service property to generic service class
    """
    service_object_id = ""


class OpsviewServer(GenericServer):
    """
       special treatment for Opsview XML based API
    """
    TYPE = 'Opsview'

    # Arguments available for submitting check results
    SUBMIT_CHECK_RESULT_ARGS = ["comment"]

    # autologin is used only by Centreon
    DISABLED_CONTROLS = ["input_checkbutton_use_autologin",
                         "label_autologin_key",
                         "input_entry_autologin_key",
                         "input_checkbutton_use_display_name_host",
                         "input_checkbutton_use_display_name_service",
                         # turn off options on ack box
                         "input_checkbutton_persistent_comment",
                         "input_checkbutton_acknowledge_all_services",
                         # turn off options on downloads box
                         "hbox_duration",
                         "input_radiobutton_type_fixed",
                         "input_radiobutton_type_fixed",
                         "input_spinbutton_duration_hours",
                         "input_spinbutton_duration_minutes"
                         "input_entry_author",
                         # turn off cgi url config
                         "input_entry_monitor_cgi_url",
                         ]


    def init_HTTP(self):
        if self.HTTPheaders == {}:
            GenericServer.init_HTTP(self)

        # get cookie to access Opsview web interface to access Opsviews Nagios part
        if len(self.Cookie) == 0:

            if str(self.conf.debug_mode) == "True":
                self.Debug(server=self.get_name(), debug="Fetching Login token")

            # put all necessary data into url string
            logindata = urllib.urlencode({"username":self.get_username(),\
                             "password":self.get_password(),})

            # the following is necessary for Opsview servers
            # get cookie from login page via url retrieving as with other urls
            try:
                # login and get cookie
                urlcontent = self.urlopener.open(self.monitor_url + "/rest/login", logindata)
                resp = literal_eval(urlcontent.read().decode("utf8", errors="ignore"))

                if str(self.conf.debug_mode) == "True":
                    self.Debug(server=self.get_name(), debug="Login Token: " + resp.get('token') )

                self.HTTPheaders["raw"] = {"Accept":"application/json","Content-Type":"application/json", "X-Opsview-Username":self.get_username(), "X-Opsview-Token":resp.get('token')}

                urlcontent.close()
            except:
                self.Error(sys.exc_info())

    def init_config(self):
        """
        dummy init_config, called at thread start, not really needed here, just omit extra properties
        """
        pass


    def get_start_end(self, host):
        """
        Set a default of starttime of "now" and endtime is "now + 24 hours"
        directly from web interface
        """
        start = datetime.now()
        end = datetime.now() + timedelta(hours=24)

        return str(start.strftime("%Y-%m-%d %H:%M:%S")), str(end.strftime("%Y-%m-%d %H:%M:%S"))

    def _set_downtime(self, host, service, author, comment, fixed, start_time, end_time, hours, minutes):
        url = self.monitor_url + "/rest/downtime?"

        data = dict();
        data["comment"]=str(comment)
        data["starttime"]=start_time
        data["endtime"]=end_time

        if service == "":
            data["hst.hostname"]=str(host)

        if service != "":
            data["svc.hostname"]=str(host)
            data["svc.servicename"]=str(service)

        cgi_data = urllib.urlencode(data)

        self.Debug(server=self.get_name(), debug="Downtime url: " + url)
        self.FetchURL(url + cgi_data, giveback="raw", cgi_data=({ }))

    def _set_submit_check_result(self, host, service, state, comment, check_output, performance_data):
        """
        worker for submitting check result
        """
        url = self.monitor_url + "/rest/status?"

        data = dict();
        data["comment"]=str(comment)
        data["new_state"]=({"ok":0,"warning":1,"critical":2,"unknown":3})[state]

        if service == "":
            data["hst.hostname"]=str(host)

        if service != "":
            data["svc.hostname"]=str(host)
            data["svc.servicename"]=str(service)

        cgi_data = urllib.urlencode(data)

        self.Debug(server=self.get_name(), debug="Submit result url: " + url)
        self.FetchURL(url + cgi_data, giveback="raw", cgi_data=({ }))


    def _set_acknowledge(self, host, service, author, comment, sticky, notify, persistent, all_services=[]):
        """
        Sumit acknowledgement for host or service
        """
        url = self.monitor_url + "/rest/acknowledge?"

        data=dict();
        data["notify"]=str(notify)
        data["sticky"]=str(sticky)
        data["comment"]=str(comment)
        data["host"]=str(host)

        if service != "":
            data["servicecheck"]=str(service)

        cgi_data = urllib.urlencode(data)

        self.Debug(server=self.get_name(), debug="ACK url: " + url)
        self.FetchURL(url + cgi_data, giveback="raw", cgi_data=({ }))

    def _set_recheck(self, host, service):
        """
        Sumit recheck request for host or service
        """
        url = self.monitor_url + "/rest/recheck?"

        data=dict();
        data["host"]=str(host)

        if service != "":
            data["servicecheck"]=str(service)

        cgi_data = urllib.urlencode(data)

        self.Debug(server=self.get_name(), debug="Recheck url: " + url)
        self.FetchURL(url + cgi_data, giveback="raw", cgi_data=({ }))

    def _get_status(self):
        """
        Get status from Opsview Server
        """
        # following XXXX to get ALL services in ALL states except OK
        # because we filter them out later
        # the REST API gets all host and service info in one call
        try:
            result = self.FetchURL(self.monitor_url + "/rest/status/service?state=1&state=2&state=3", giveback="raw")
            data = json.loads(result.result)

            if str(self.conf.debug_mode) == "True":
                self.Debug(server=self.get_name(), debug="Fetched JSON: " + pprint.pformat(data))

            #for host in xmlobj.opsview.findAll("item"):
            for host in data["list"]:
                self.new_hosts[host["name"]] = GenericHost()
                self.new_hosts[host["name"]].name = str(host["name"])
                self.new_hosts[host["name"]].server = self.name
                # states come in lower case from Opsview
                self.new_hosts[host["name"]].status = str(host["state"].upper())
                self.new_hosts[host["name"]].status_type = str(host["state_type"])
                self.new_hosts[host["name"]].last_check = datetime.fromtimestamp(int(host["last_check"])).strftime("%Y-%m-%d %H:%M:%S %z")
                self.new_hosts[host["name"]].duration = Actions.HumanReadableDurationFromSeconds(host["state_duration"])
                self.new_hosts[host["name"]].attempt = host["current_check_attempt"]+ "/" + host["max_check_attempts"]
                self.new_hosts[host["name"]].status_information = host["output"].replace("\n", " ")

                # if host is in downtime add it to known maintained hosts
                if host["downtime"] == "2":
                    self.new_hosts[host["name"]].scheduled_downtime = True
                if host.has_key("acknowledged"):
                    self.new_hosts[host["name"]].acknowledged = True
                if host.has_key("flapping"):
                    self.new_hosts[host["name"]].flapping = True

                #services
                for service in host["services"]:
                    self.new_hosts[host["name"]].services[service["name"]] = OpsviewService()
                    self.new_hosts[host["name"]].services[service["name"]].host = str(host["name"])
                    self.new_hosts[host["name"]].services[service["name"]].name = service["name"]
                    self.new_hosts[host["name"]].services[service["name"]].server = self.name

                    # states come in lower case from Opsview
                    self.new_hosts[host["name"]].services[service["name"]].status = service["state"].upper()
                    self.new_hosts[host["name"]].services[service["name"]].status_type = service["state_type"]
                    self.new_hosts[host["name"]].services[service["name"]].last_check = datetime.fromtimestamp(int(service["last_check"])).strftime("%Y-%m-%d %H:%M:%S %z")
                    self.new_hosts[host["name"]].services[service["name"]].duration = Actions.HumanReadableDurationFromSeconds(service["state_duration"])
                    self.new_hosts[host["name"]].services[service["name"]].attempt = service["current_check_attempt"]+ "/" + service["max_check_attempts"]
                    self.new_hosts[host["name"]].services[service["name"]].status_information= service["output"].replace("\n", " ")
                    if service["downtime"] == "2":
                        self.new_hosts[host["name"]].services[service["name"]].scheduled_downtime = True
                    if service.has_key("acknowledged"):
                        self.new_hosts[host["name"]].services[service["name"]].acknowledged = True
                    if service.has_key("flapping"):
                        self.new_hosts[host["name"]].services[service["name"]].flapping = True

                    # extra opsview id for service, needed for submitting check results
                    self.new_hosts[host["name"]].services[service["name"]].service_object_id = service["service_object_id"]

        except:
            # set checking flag back to False
            self.isChecking = False
            result, error = self.Error(sys.exc_info())
            return Result(result=result, error=error)

        #dummy return in case all is OK
        return Result()

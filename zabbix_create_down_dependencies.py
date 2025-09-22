import logging
from collections import defaultdict
import urllib3
from zabbix_dependencies import ZabbixAPI, ZABBIX_URL, API_TOKEN, TIMEOUT, ZabbixAPIError

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_hosts_by_group(api, group_name):
    """Return list of hosts (dicts with hostid, name, status) for a group"""
    result = api.call("hostgroup.get", {
        "filter": {"name": [group_name]},
        "output": ["name"],
        "monitored_hosts": True,
        "selectHosts": ["hostid", "name", "status"]
    })
    if result:
        return [h for h in result[0].get("hosts", []) if h.get("status") == "0"]
    return []

def group_hosts_by_site(hosts):
    """Return a dict: site_name -> list of hosts (dicts with hostid, name)"""
    sites = defaultdict(list)
    for host in hosts:
        name = host["name"]
        site = name.split("-")[0] if "-" in name else name
        sites[site].append(host)
    return sites

def get_down_triggers_for_host(api, host):
    """Return list of triggerids for '{HOST.HOST} Down' triggers for a single host"""
    host_name = host["name"]
    triggers = api.call("trigger.get", {
        "filter": {"host": [host_name]},
        "search": {"description": "{HOST.HOST} Down"},
        "output": ["triggerid", "description"]
    })
    return [trig["triggerid"] for trig in triggers]

def get_down_triggers_for_hosts_with_names(api, hosts):
    """
    Return list of tuples: (triggerid, fw_host_name) for all '{HOST.HOST} Down' triggers for given hosts
    """
    trigger_info = []
    for host in hosts:
        host_name = host["name"]
        triggers = api.call("trigger.get", {
            "filter": {"host": [host_name]},
            "search": {"description": "{HOST.HOST} Down"},
            "output": ["triggerid", "description"]
        })
        for trig in triggers:
            trigger_info.append((trig["triggerid"], host_name))
    return trigger_info

def main():
    api = ZabbixAPI(ZABBIX_URL, API_TOKEN, TIMEOUT)
    try:
        # 1. Get all switch hosts (Branch-low)
        switch_hosts = get_hosts_by_group(api, "Branch-low")
        switch_sites = group_hosts_by_site(switch_hosts)

        # 2. Get all FW hosts (Branch-high)
        fw_hosts = get_hosts_by_group(api, "Branch-high")
        fw_sites = group_hosts_by_site(fw_hosts)

        logger.info(f"Found {len(switch_sites)} switch sites and {len(fw_sites)} FW sites.")

        # 3. For each site, create dependencies
        for site, switches in switch_sites.items():
            # FW hosts for this site
            fw_hosts_site = [h for h in fw_hosts if h["name"].startswith(site + "-")]
            if not fw_hosts_site:
                logger.warning(f"No FW hosts found for site {site}, skipping.")
                continue
            fw_down_triggers_info = get_down_triggers_for_hosts_with_names(api, fw_hosts_site)
            if not fw_down_triggers_info:
                logger.warning(f"No FW 'Down' triggers found for site {site}, skipping.")
                continue

            logger.info(f"Site {site}: {len(switches)} switches, {len(fw_hosts_site)} FWs, {len(fw_down_triggers_info)} FW Down triggers.")

            for switch in switches:
                switchid = switch["hostid"]
                switch_name = switch["name"]
                # Only "Down" triggers for this switch
                down_triggerids = get_down_triggers_for_host(api, switch)
                for triggerid in down_triggerids:
                    for fw_triggerid, fw_host_name in fw_down_triggers_info:
                        if triggerid == fw_triggerid:
                            continue  # Don't depend on itself
                        ok = api.update_trigger_dependencies(triggerid, fw_triggerid)
                        if ok:
                            logger.info(f"Added dependency: {switch_name} Down trigger {triggerid} -> FW {fw_host_name} trigger {fw_triggerid}")
                        else:
                            logger.error(f"Failed to add dependency: {switch_name} Down trigger {triggerid} -> FW {fw_host_name} trigger {fw_triggerid}")

        logger.info("Bulk site dependency creation complete.")

    except ZabbixAPIError as e:
        logger.error(f"Zabbix API error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()
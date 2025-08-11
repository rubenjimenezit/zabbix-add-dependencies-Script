#!/usr/bin/env python3
import requests
import json
import sys
import logging
from typing import Dict, List, Any, Optional

# === CONFIGURATION ===
ZABBIX_URL = "http://localhost:8080/api_jsonrpc.php"  # Change to your Zabbix API URL
API_TOKEN = ""  # Your API token
TIMEOUT = 30  # Request timeout in seconds
# =====================

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ZabbixAPIError(Exception):
    """Custom exception for Zabbix API errors"""
    pass


class ZabbixAPI:
    """Zabbix API client"""
    
    def __init__(self, url: str, token: str, timeout: int = 30):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()
    
    def call(self, method: str, params: Dict[str, Any]) -> Any:
        """Make a Zabbix API call"""
        headers = {
            "Content-Type": "application/json-rpc"
        }
        
        # Don't send Authorization header for apiinfo.version
        if method != "apiinfo.version":
            headers["Authorization"] = f"Bearer {self.token}"
        
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        try:
            logger.debug(f"Calling API method: {method}")
            response = self.session.post(
                self.url,
                headers=headers,
                data=json.dumps(payload),
                timeout=self.timeout
            )
            response.raise_for_status()
            
        except requests.exceptions.RequestException as e:
            raise ZabbixAPIError(f"HTTP request failed: {e}")
        
        try:
            result = response.json()
        except json.JSONDecodeError as e:
            raise ZabbixAPIError(f"Invalid JSON response: {e}")
        
        if "error" in result:
            error_msg = result["error"].get("message", "Unknown error")
            error_data = result["error"].get("data", "")
            raise ZabbixAPIError(f"API error in {method}: {error_msg} {error_data}")
        
        return result.get("result")
    
    def get_version(self) -> str:
        """Get Zabbix API version"""
        return self.call("apiinfo.version", {})
    
    def get_host_triggers(self, hostid: str, include_discovered: bool = False) -> List[Dict[str, Any]]:
        """Get all enabled triggers for a host"""
        # Get all triggers first
        all_triggers = self.call("trigger.get", {
            "hostids": hostid,
            "output": ["triggerid", "description", "priority", "status", "flags"],
            "filter": {"status": 0},  # Only enabled triggers
            "sortfield": "description"
        })
        
        # If include_discovered is True, return all triggers without filtering
        if include_discovered:
            logger.info(f"Found {len(all_triggers)} total triggers (including discovered)")
            return all_triggers
        
        # Filter out discovered triggers 
        normal_triggers = []
        discovered_count = 0
        
        for trigger in all_triggers:
            # Multiple ways to check if trigger is discovered
            flags = str(trigger.get("flags", "0"))
            description = trigger.get("description", "")
            
            # Check flags (4 = discovered)
            is_discovered = flags == "4"
            
            # Additional heuristic checks for discovered triggers
            # These patterns are common in network device LLD triggers
            discovered_patterns = [
                "Twe1/0/",  # Interface patterns from your logs
                "Te1/0/",
                "Gi1/0/",
                "Fa1/0/",
                "{#",       # LLD macro patterns
                "}(",       # Common in interface descriptions
            ]
            
            # Check if description matches discovered trigger patterns
            if any(pattern in description for pattern in discovered_patterns):
                is_discovered = True
            
            if is_discovered:
                discovered_count += 1
                logger.debug(f"Skipping discovered trigger (flags={flags}): {description}")
                continue
                
            normal_triggers.append(trigger)
        
        logger.info(f"Found {len(all_triggers)} total triggers, {discovered_count} discovered (skipped), {len(normal_triggers)} normal")
        return normal_triggers
    
    def get_trigger_info(self, triggerid: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific trigger"""
        triggers = self.call("trigger.get", {
            "triggerids": triggerid,
            "output": ["triggerid", "description", "priority", "status"]
        })
        return triggers[0] if triggers else None
    
    def get_trigger_prototype_for_discovered_trigger(self, discovered_triggerid: str) -> Optional[str]:
        """Find the trigger prototype ID that created a discovered trigger"""
        try:
            # Get the discovered trigger with more details
            trigger = self.call("trigger.get", {
                "triggerids": discovered_triggerid,
                "output": ["triggerid", "templateid", "description", "expression"],
                "selectItems": ["itemid", "hostid", "key_"],
                "selectHosts": ["hostid", "host"]
            })
            
            if not trigger:
                logger.error(f"Discovered trigger {discovered_triggerid} not found")
                return None
                
            trigger_data = trigger[0]
            logger.debug(f"Discovered trigger data: {trigger_data}")
            
            # Method 1: Check if trigger has templateid pointing to prototype
            if trigger_data.get("templateid"):
                template_triggerid = trigger_data["templateid"]
                logger.debug(f"Found templateid: {template_triggerid}")
                
                # Check if this template trigger is actually a prototype
                template_trigger = self.call("trigger.get", {
                    "triggerids": template_triggerid,
                    "output": ["triggerid", "flags"]
                })
                
                if template_trigger:
                    flags = str(template_trigger[0].get("flags", "0"))
                    logger.debug(f"Template trigger flags: {flags}")
                    if flags == "2":  # flags=2 means prototype
                        return template_triggerid
            
            # Method 2: Find prototypes by searching for similar expressions on template
            items = trigger_data.get("items", [])
            if not items:
                logger.error(f"No items found for trigger {discovered_triggerid}")
                return None
            
            # Get host information
            hosts = trigger_data.get("hosts", [])
            if not hosts:
                logger.error(f"No host found for trigger {discovered_triggerid}")
                return None
                
            host_id = hosts[0]["hostid"]
            logger.debug(f"Host ID: {host_id}")
            
            # Get the host's templates
            host_templates = self.call("host.get", {
                "hostids": host_id,
                "selectParentTemplates": ["templateid", "host"]
            })
            
            if not host_templates or not host_templates[0].get("parentTemplates"):
                logger.error(f"No templates found for host {host_id}")
                return None
                
            templates = host_templates[0]["parentTemplates"]
            logger.debug(f"Found {len(templates)} templates")
            
            # Search for trigger prototypes in each template
            for template in templates:
                template_id = template["templateid"]
                logger.debug(f"Searching prototypes in template: {template['host']} ({template_id})")
                
                # Get all trigger prototypes from this template
                prototypes = self.call("triggerprototype.get", {
                    "templateids": template_id,
                    "output": ["triggerid", "description", "expression"],
                    "selectItems": ["itemid", "key_"]
                })
                
                if not prototypes:
                    continue
                    
                logger.debug(f"Found {len(prototypes)} prototypes in template {template['host']}")
                
                # Try to match by description pattern or item keys
                discovered_desc = trigger_data.get("description", "")
                discovered_items = trigger_data.get("items", [])
                
                for prototype in prototypes:
                    prototype_desc = prototype.get("description", "")
                    prototype_items = prototype.get("items", [])
                    
                    # Method 2a: Match by description pattern (remove LLD macros)
                    # Convert discovered description back to prototype pattern
                    # This is complex but let's try basic matching first
                    
                    # Method 2b: Match by item keys
                    if discovered_items and prototype_items:
                        discovered_key = discovered_items[0].get("key_", "")
                        prototype_key = prototype_items[0].get("key_", "")
                        
                        # Remove LLD instance parts to match prototype
                        # For example: convert "ifOperStatus[GigabitEthernet1/0/1]" to "ifOperStatus[{#IFNAME}]"
                        if prototype_key and discovered_key:
                            # Simple heuristic: if the base key matches
                            prototype_base = prototype_key.split('[')[0] if '[' in prototype_key else prototype_key
                            discovered_base = discovered_key.split('[')[0] if '[' in discovered_key else discovered_key
                            
                            if prototype_base == discovered_base:
                                logger.info(f"Found matching prototype by item key: {prototype['triggerid']}")
                                return prototype["triggerid"]
            
            # Method 3: Search all prototypes and try to match by expression pattern
            all_prototypes = self.call("triggerprototype.get", {
                "output": ["triggerid", "description", "expression"],
                "selectItems": ["itemid", "key_"]
            })
            
            logger.debug(f"Searching through {len(all_prototypes)} total prototypes")
            
            # This is a more complex matching - would need detailed analysis
            # For now, we'll skip this method
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to find prototype for discovered trigger {discovered_triggerid}: {e}")
            return None

    def update_trigger_dependencies(self, triggerid: str, parent_triggerid: str) -> bool:
        """Add a dependency to a normal trigger using the correct API method"""
        try:
            # First, get the current trigger configuration
            current_trigger = self.call("trigger.get", {
                "triggerids": triggerid,
                "output": ["triggerid", "dependencies"],
                "selectDependencies": ["triggerid"]
            })
            
            if not current_trigger:
                logger.error(f"Trigger {triggerid} not found")
                return False
            
            # Get current dependencies
            current_dependencies = current_trigger[0].get("dependencies", [])
            
            # Check if dependency already exists
            for dep in current_dependencies:
                if dep["triggerid"] == parent_triggerid:
                    logger.info(f"Dependency already exists for trigger {triggerid}")
                    return True
            
            # Add the new dependency to existing ones
            new_dependencies = current_dependencies + [{"triggerid": parent_triggerid}]
            
            # Update the trigger with new dependencies
            self.call("trigger.update", {
                "triggerid": triggerid,
                "dependencies": new_dependencies
            })
            return True
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to update trigger {triggerid}: {error_msg}")
            return False

    def update_trigger_prototype_dependencies(self, prototype_id: str, parent_triggerid: str, hostid: str) -> bool:
        """Add dependencies to a trigger prototype, creating template trigger if needed"""
        try:
            # First check if the parent trigger is also a prototype/template trigger
            parent_trigger = self.call("trigger.get", {
                "triggerids": parent_triggerid,
                "output": ["triggerid", "flags", "templateid"],
                "selectHosts": ["hostid", "status"]
            })
            
            if not parent_trigger:
                logger.error(f"Parent trigger {parent_triggerid} not found")
                return False
                
            parent_flags = str(parent_trigger[0].get("flags", "0"))
            parent_hosts = parent_trigger[0].get("hosts", [])
            
            # Check if parent is a host trigger (not template/prototype)
            is_host_trigger = False
            if parent_hosts:
                for host in parent_hosts:
                    if host.get("status") == "0":  # 0 = monitored host, 3 = template
                        is_host_trigger = True
                        break
            
            template_parent_triggerid = parent_triggerid
            
            if is_host_trigger:
                logger.info(f"Parent trigger is on host, need to create template version...")
                
                # Find the template for this host
                template_id = self.find_template_for_host(hostid)
                if not template_id:
                    logger.error(f"Cannot find template for host {hostid}")
                    return False
                
                # Create template trigger based on host trigger
                template_parent_triggerid = self.create_template_trigger_from_host_trigger(parent_triggerid, template_id)
                if not template_parent_triggerid:
                    logger.error(f"Failed to create template trigger")
                    return False
                    
                logger.info(f"Using template trigger {template_parent_triggerid} for dependencies")
            
            # Get current prototype configuration
            current_prototype = self.call("triggerprototype.get", {
                "triggerids": prototype_id,
                "output": ["triggerid", "dependencies"],
                "selectDependencies": ["triggerid"]
            })
            
            if not current_prototype:
                logger.error(f"Trigger prototype {prototype_id} not found")
                return False
            
            # Get current dependencies
            current_dependencies = current_prototype[0].get("dependencies", [])
            
            # Check if dependency already exists
            for dep in current_dependencies:
                if dep["triggerid"] == template_parent_triggerid:
                    logger.info(f"Dependency already exists for prototype {prototype_id}")
                    return True
            
            # Add the new dependency to existing ones
            new_dependencies = current_dependencies + [{"triggerid": template_parent_triggerid}]
            
            # Update the prototype with new dependencies
            self.call("triggerprototype.update", {
                "triggerid": prototype_id,
                "dependencies": new_dependencies
            })
            
            logger.info(f"✅ Successfully added dependency to prototype {prototype_id}")
            return True
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to update trigger prototype {prototype_id}: {error_msg}")
            return False
        """Add a dependency to a trigger using the correct API method"""
        try:
            # First, get the current trigger configuration
            current_trigger = self.call("trigger.get", {
                "triggerids": triggerid,
                "output": ["triggerid", "dependencies"],
                "selectDependencies": ["triggerid"]
            })
            
            if not current_trigger:
                logger.error(f"Trigger {triggerid} not found")
                return False
            
            # Get current dependencies
            current_dependencies = current_trigger[0].get("dependencies", [])
            
            # Check if dependency already exists
            for dep in current_dependencies:
                if dep["triggerid"] == parent_triggerid:
                    logger.info(f"Dependency already exists for trigger {triggerid}")
                    return True
            
            # Add the new dependency to existing ones
            new_dependencies = current_dependencies + [{"triggerid": parent_triggerid}]
            
            # Update the trigger with new dependencies
            self.call("trigger.update", {
                "triggerid": triggerid,
                "dependencies": new_dependencies
            })
            return True
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to update trigger {triggerid}: {error_msg}")
            return False
    
    def create_template_trigger_from_host_trigger(self, host_triggerid: str, template_id: str) -> Optional[str]:
        """Create a template trigger based on a host trigger"""
        try:
            # Get the host trigger details
            host_trigger = self.call("trigger.get", {
                "triggerids": host_triggerid,
                "output": ["triggerid", "description", "expression", "priority", "comments"],
                "selectItems": ["itemid", "key_", "hostid"],
                "selectHosts": ["hostid", "host"]
            })
            
            if not host_trigger:
                logger.error(f"Host trigger {host_triggerid} not found")
                return None
                
            trigger_data = host_trigger[0]
            logger.info(f"Creating template trigger based on: {trigger_data['description']}")
            
            # Get template items that correspond to the host items
            host_items = trigger_data.get("items", [])
            if not host_items:
                logger.error(f"No items found for trigger {host_triggerid}")
                return None
            
            # Build the template expression by replacing host items with template items
            template_expression = trigger_data["expression"]
            
            for host_item in host_items:
                host_item_id = host_item["itemid"]
                item_key = host_item["key_"]
                
                # Find corresponding template item
                template_items = self.call("item.get", {
                    "templateids": template_id,
                    "filter": {"key_": item_key},
                    "output": ["itemid", "key_"]
                })
                
                if template_items:
                    template_item_id = template_items[0]["itemid"]
                    # Replace host item ID with template item ID in expression
                    template_expression = template_expression.replace(f":{host_item_id}:", f":{template_item_id}:")
                    logger.debug(f"Replaced item {host_item_id} with {template_item_id}")
                else:
                    logger.warning(f"Could not find template item for key: {item_key}")
            
            # Create the template trigger
            template_trigger_desc = f"Template: {trigger_data['description']}"
            
            result = self.call("trigger.create", {
                "description": template_trigger_desc,
                "expression": template_expression,
                "priority": trigger_data.get("priority", 3),
                "comments": f"Auto-created template trigger for dependencies. Based on host trigger {host_triggerid}. {trigger_data.get('comments', '')}",
                "status": 0  # Enabled
            })
            
            if result and result.get("triggerids"):
                template_triggerid = result["triggerids"][0]
                logger.info(f"✅ Created template trigger: {template_trigger_desc} (ID: {template_triggerid})")
                return template_triggerid
            else:
                logger.error(f"Failed to create template trigger")
                return None
                
        except Exception as e:
            logger.error(f"Failed to create template trigger: {e}")
            return None
    
    def find_template_for_host(self, hostid: str) -> Optional[str]:
        """Find the primary template for a host (used for discovered triggers)"""
        try:
            # Get host's templates
            host_templates = self.call("host.get", {
                "hostids": hostid,
                "selectParentTemplates": ["templateid", "host", "name"]
            })
            
            if not host_templates or not host_templates[0].get("parentTemplates"):
                logger.error(f"No templates found for host {hostid}")
                return None
                
            templates = host_templates[0]["parentTemplates"]
            logger.info(f"Host has {len(templates)} template(s)")
            
            # For now, return the first template
            # In a more sophisticated version, you could:
            # 1. Ask user to choose
            # 2. Find template with most LLD rules
            # 3. Use heuristics to find the "main" template
            
            if templates:
                primary_template = templates[0]
                logger.info(f"Using template: {primary_template['name']} ({primary_template['templateid']})")
                return primary_template["templateid"]
                
            return None
            
        except Exception as e:
            logger.error(f"Failed to find template for host {hostid}: {e}")
            return None

    def get_host_info(self, hostid: str) -> Optional[Dict[str, Any]]:
        """Get host information"""
        hosts = self.call("host.get", {
            "hostids": hostid,
            "output": ["hostid", "host", "name"]
        })
        return hosts[0] if hosts else None
        """Get host information"""
        hosts = self.call("host.get", {
            "hostids": hostid,
            "output": ["hostid", "host", "name"]
        })
        return hosts[0] if hosts else None


def validate_arguments() -> tuple[str, str, bool]:
    """Validate command line arguments"""
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print(f"Usage: {sys.argv[0]} <hostid> <parent_triggerid> [--include-discovered]")
        print("\nDescription:")
        print("  hostid: The ID of the host whose triggers will depend on the parent")
        print("  parent_triggerid: The ID of the trigger that others will depend on")
        print("  --include-discovered: Optional flag to attempt processing discovered triggers")
        print("\nNote: Processing discovered triggers requires finding their prototypes,")
        print("      which may fail due to Zabbix dependency restrictions.")
        print("      Discovered triggers can only depend on template-level triggers,")
        print("      not host-level triggers. Use with caution.")
        sys.exit(1)
    
    hostid = sys.argv[1].strip()
    parent_triggerid = sys.argv[2].strip()
    include_discovered = len(sys.argv) == 4 and sys.argv[3] == "--include-discovered"
    
    if not hostid.isdigit():
        print(f"Error: hostid '{hostid}' must be a number")
        sys.exit(1)
    
    if not parent_triggerid.isdigit():
        print(f"Error: parent_triggerid '{parent_triggerid}' must be a number")
        sys.exit(1)
    
    return hostid, parent_triggerid, include_discovered


def main():
    """Main function"""
    try:
        # Validate arguments
        hostid, parent_triggerid, include_discovered = validate_arguments()
        
        # Initialize API client
        logger.info("Connecting to Zabbix API...")
        api = ZabbixAPI(ZABBIX_URL, API_TOKEN, TIMEOUT)
        
        # Test connection and get version
        try:
            version = api.get_version()
            logger.info(f"Connected to Zabbix API version: {version}")
        except ZabbixAPIError as e:
            logger.error(f"Failed to connect to Zabbix API: {e}")
            sys.exit(1)
        
        # Validate host exists
        logger.info(f"Validating host ID: {hostid}")
        host_info = api.get_host_info(hostid)
        if not host_info:
            logger.error(f"Host with ID '{hostid}' not found")
            sys.exit(1)
        
        logger.info(f"Host found: {host_info['name']} ({host_info['host']})")
        
        # Validate parent trigger exists
        logger.info(f"Validating parent trigger ID: {parent_triggerid}")
        parent_trigger = api.get_trigger_info(parent_triggerid)
        if not parent_trigger:
            logger.error(f"Parent trigger with ID '{parent_triggerid}' not found")
            sys.exit(1)
        
        logger.info(f"Parent trigger found: {parent_trigger['description']}")
        
        # Get triggers for the host
        if include_discovered:
            logger.info(f"Fetching ALL triggers for host {hostid} (including discovered)...")
            triggers = api.get_host_triggers(hostid, include_discovered=True)
        else:
            logger.info(f"Fetching normal triggers for host {hostid} (excluding discovered)...")
            triggers = api.get_host_triggers(hostid, include_discovered=False)
        
        if not triggers:
            logger.warning(f"No enabled triggers found for host {hostid}")
            sys.exit(0)
        
        logger.info(f"Found {len(triggers)} enabled trigger(s)")
        
        # Add dependencies
        success_count = 0
        skip_count = 0
        error_count = 0
        prototype_success_count = 0
        prototype_error_count = 0
        
        for trigger in triggers:
            trigger_id = trigger["triggerid"]
            trigger_desc = trigger["description"]
            flags = str(trigger.get("flags", "0"))
            
            # Skip if this is the parent trigger itself
            if trigger_id == parent_triggerid:
                logger.info(f"Skipping parent trigger: {trigger_desc}")
                skip_count += 1
                continue
            
            # Handle discovered triggers differently
            if flags == "4":
                logger.info(f"Found discovered trigger: {trigger_desc}")
                logger.info("Attempting to find and update the trigger prototype...")
                
                # Find the prototype that created this discovered trigger
                prototype_id = api.get_trigger_prototype_for_discovered_trigger(trigger_id)
                
                if prototype_id:
                    logger.info(f"Found prototype ID: {prototype_id}")
                    if api.update_trigger_prototype_dependencies(prototype_id, parent_triggerid, hostid):
                        prototype_success_count += 1
                        logger.info(f"✅ Successfully updated prototype for discovered trigger: {trigger_desc}")
                    else:
                        prototype_error_count += 1
                        logger.error(f"❌ Failed to update prototype for discovered trigger: {trigger_desc}")
                else:
                    # Alternative: Log the discovered trigger for manual handling
                    logger.warning(f"⚠️  Could not find prototype for discovered trigger: {trigger_desc}")
                    logger.warning(f"   Trigger ID: {trigger_id}")
                    logger.warning(f"   Consider manually updating the LLD rule or trigger prototype")
                    logger.warning(f"   Or modify the template that generates this trigger")
                    prototype_error_count += 1
                continue
            
            # Handle normal triggers
            logger.info(f"Adding dependency to normal trigger: {trigger_desc}")
            
            if api.update_trigger_dependencies(trigger_id, parent_triggerid):
                success_count += 1
                logger.info(f"✅ Successfully added dependency for trigger: {trigger_desc}")
            else:
                error_count += 1
                logger.error(f"❌ Failed to add dependency for trigger: {trigger_desc}")
        
        # Summary
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        print(f"Total triggers found: {len(triggers)}")
        print(f"Normal trigger dependencies added: {success_count}")
        print(f"Prototype dependencies added: {prototype_success_count}")
        print(f"Skipped (parent trigger): {skip_count}")
        print(f"Normal trigger errors: {error_count}")
        print(f"Prototype update errors: {prototype_error_count}")
        
        total_success = success_count + prototype_success_count
        total_errors = error_count + prototype_error_count
        
        if prototype_success_count > 0:
            print(f"\nℹ️  Note: {prototype_success_count} trigger prototypes were updated")
            print("   This will apply dependencies to future discovered triggers from those prototypes")
        
        if total_success > 0:
            print(f"\n✅ Successfully processed {total_success} triggers/prototypes!")
            
        if total_errors == 0 and total_success > 0:
            print("🎯 All triggers now have dependencies configured!")
            sys.exit(0)
        elif total_errors > 0:
            print(f"\n⚠️  Completed with {total_errors} error(s)")
            sys.exit(1)
        else:
            print("\n ℹ️ No dependencies were added (all triggers were skipped)")
            sys.exit(0)
            
    except KeyboardInterrupt:
        logger.info("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

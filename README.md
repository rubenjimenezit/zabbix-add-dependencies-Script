# zabbix-add-dependencies-Script
A Python script to automatically create trigger dependencies in Zabbix, establishing hierarchical relationships where child triggers are suppressed when parent triggers fire


Zabbix Trigger Dependencies Manager

Automate the creation of trigger dependencies in Zabbix to build hierarchical monitoring structures. This script adds dependencies to all triggers on a specified host, making them depend on a parent trigger to reduce alert noise.

✨ Features:
- Bulk dependency creation for host triggers
- Comprehensive error handling and logging
- Smart filtering of discovered triggers
- Template trigger validation
- Detailed operation reporting

⚠️ Limitation: This script cannot handle prototype triggers due to Zabbix API restrictions. Discovered triggers are automatically filtered out to prevent errors.

Perfect for network monitoring scenarios where you want regular host triggers to depend on device availability.

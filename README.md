# Zabbix Trigger Dependencies Automation Script

A professional Python utility for automating hierarchical trigger dependencies in Zabbix. Effortlessly configure parent/child relationships so that child triggers are suppressed when a parent trigger is active, streamlining your monitoring and alerting workflows.

---

## Overview

**Zabbix Trigger Dependencies Manager**  
This script automates the creation of trigger dependencies for all triggers on a specified host, linking them to a designated parent trigger. It is designed to help Zabbix administrators efficiently build scalable, hierarchical monitoring structures, ensuring that alerts are meaningful and actionable.

---

## 🚀 Key Features

- **Bulk Dependency Management:** Automatically add dependencies for all host triggers in one operation.
- **Robust Error Handling & Logging:** Comprehensive logs and informative error messages to simplify troubleshooting.
- **Intelligent Trigger Filtering:** Excludes unsupported prototype triggers and validates templates for reliability.
- **Detailed Reporting:** Clear summaries of actions taken, including success and failure counts.
- **Safe Operation:** Prevents API errors by automatically filtering out unsupported triggers.

---

## ⚠️ Limitations

- **Prototype Trigger Support:** Due to Zabbix API restrictions, prototype triggers (from discovery rules) cannot be managed by this script. These are automatically excluded from operations.

---

## Use Cases

- **Network Monitoring:** Create dependencies so that regular host triggers are suppressed when a device availability trigger fires.
- **Service Management:** Minimize alert noise by structuring alerts according to service hierarchies.
- **Template Validation:** Ensure only valid triggers are included in dependency operations.

---

## 📦 Usage

```bash
python3 zabbix_dependencies.py <hostid> <parent_triggerid>
```

- `<hostid>`: The Zabbix host identifier for which dependencies should be created.
- `<parent_triggerid>`: The parent trigger ID that all other triggers will depend on.

---

## Example

```bash
python3 zabbix_dependencies.py 10101 20202
```

This will create dependencies for all triggers on host `10101`, making them depend on trigger `20202`.

---

## Requirements

- Python 3.x
- Zabbix API access
- Valid Zabbix credentials (configured within the script or environment)
---

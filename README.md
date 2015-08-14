# chargeback-backoffice
Backoffice scripts and tools to implement BSS services with StackOps Chargeback

All these tools are up and running in https://cirrusflex.com. 

# Tools
## create_invoice.py
### Overview
This process integrates the Chargeback system with a third party SaaS invoicing system, Debitdoor. This invoicing system is one of the most simple but has one of the best documented REST API, making integration really simple.

The process extracts the consume of the past month passed as argument and passes the consume to the invoicing system. If the customer does not exists, it also creates it in the remote system. if the information of the customer changes, then it's updated in the remote system too. 

The invoicing system creates a valid invoice and generates a PDF. This script also downloads the PDF and rename it with a unique name, uploading it afterwards to an OpenStack Swift object storage system.

### Configuration
The script needs some environment variables set first:

- PUBLIC_KEYSTONE_URL: The authentication url of your system.
- PUBLIC_CHARGEBACK_URL: The chargeback url of your system.
- ADMIN_USER: The user with enough permissions to open all accounts in your system, normally an admin user.
- ADMIN_TENANT: The tenant name of the admin user
- PUBLIC_KEYSTONE_URL_FOR_SWIFT: The authentication url of the swift system. Can be the same of PUBLIC_KEYSTONE_URL
- REGION_SWIFT_NAME: the region name of swift.
- SWIFT_USER
- SWIFT_PASSWORD
- SWIFT_TENANT_NAME
- SWIFT_CONTAINER_NAME
- SWIFT_PUBLIC_URL_PREFIX

### Prerequisites
You also need a Debitoor account and the TOKEN given to use the API.

### How to run
You can run the script as many times as needed, but keep in mind that you are creating valid invoices, so normally you should destroy the invoices created for testing.

To execute the script you have to run it as follows:

python create_invoice.py PASSWORD DEBITOOR_TOKEN dd-mm-yyyy

Where:
- PASSWORD is the admin password
- DEBITOOR_TOKEN is the token given by debitoor
- dd-mm-yyyy is the date of the last day of the billing cycle. Ex: 31-07-2015

The tool will create a log named create_invoice.log to debug the process



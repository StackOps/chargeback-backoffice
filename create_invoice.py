#   Copyright 2013-2015 STACKOPS TECHNOLOGIES S.L.
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
#   Sample chargeback <-> invoice system integration 
#   used in https://cirrusflex.com
#
# python create_invoice.py ADMIN_PASSWORD DEBITOOR_TOKEN dd-mm-yyyy
#

import sys
from keystoneclient.v2_0 import client
import logging
import requests
import json
import time
from subprocess import call
from hashlib import sha1
import hmac
import os

logging.basicConfig(filename='create_invoices.log', level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')

try:
    url = os.environ["PUBLIC_KEYSTONE_URL"]
    chargeback_url = os.environ["PUBLIC_CHARGEBACK_URL"]
    usr = os.environ["ADMIN_USER"]
    admin_tenant_name = os.environ["ADMIN_TENANT"]
    os_auth_url = os.environ["PUBLIC_KEYSTONE_URL_FOR_SWIFT"]
    os_region_name = os.environ["SWIFT_NAME"]
    os_username = os.environ["SWIFT_USER"]
    os_password = os.environ["SWIFT_PASSWORD"]
    os_tenant_id = os.environ["SWIFT_TENANT_NAME"]
    os_container = os.environ["SWIFT_CONTAINER_NAME"]
    invoice_site_prefix = os.environ["SWIFT_PUBLIC_URL_PREFIX"]
    default_country = os.environ["DEFAULT_COUNTRY"]
except KeyError as e:
    print "No variable found: {0}".format(e)
    sys.exit()

total = len(sys.argv)
cmdargs = str(sys.argv)
pasw = str(sys.argv[1])
debitoor_token = sys.argv[2]
invoice_range = int(time.mktime(time.strptime(sys.argv[3], "%d-%m-%Y")))-86400
invoice_date = time.strftime( "%Y-%m-%d", time.strptime(sys.argv[3], "%d-%m-%Y"))
multiple_zones = False
paymentTermsId = 1
max_debug = -1 # Number of testing custoemrs
default_tax_rate = 21

custom_account_id = None
total = len(sys.argv)

# European countries
EUROPEAN_COUNTRIES = ["FR", "UK", "DE", "IT"]
EUROPEAN_VAT = {'FR': 21, 'UK': 20, 'DE': 19, 'IT': 22}

# HIDDEN_PRODUCTS
HIDDEN_PRODUCTS = [1]

next_account_id = 0

SEED = "ENTER_YOUR_OWN_ENCRYPTION_SEED".encode("utf8")

LAST_CHAR = 24

FIRST_CHAR = 0

ALPHABET = '123456789abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ'
BASE_COUNT = len(ALPHABET)


def encode(secret):
    """ Returns num in a base58-encoded string """
    key = secret.encode("utf8")
    raw = SEED
    hashed = hmac.new(key, raw, sha1)
    num = int(hashed.hexdigest(), 16)
    encode = ''
    if (num < 0):
        return ''
    while (num >= BASE_COUNT):
        mod = num % BASE_COUNT
        encode = ALPHABET[mod] + encode
        num = num / BASE_COUNT
    if (num):
        encode = ALPHABET[num] + encode
    return encode[FIRST_CHAR:LAST_CHAR]


def non_exp_repr(x):
    """Return a floating point representation without exponential notation.

    Result is a string that satisfies:
        float(result)==float(x) and 'e' not in result.

    >>> non_exp_repr(1.234e-025)
    '0.00000000000000000000000012339999999999999'
    >>> non_exp_repr(-1.234e+018)
    '-1234000000000000000.0'

    >>> for e in xrange(-50,51):
    ...     for m in (1.234, 0.018, -0.89, -75.59, 100/7.0, -909):
    ...         x = m * 10 ** e
    ...         s = non_exp_repr(x)
    ...         assert 'e' not in s
    ...         assert float(x) == float(s)

    """
    s = repr(float(x))
    e_loc = s.lower().find('e')
    if e_loc == -1:
        return s

    mantissa = s[:e_loc].replace('.', '')
    exp = int(s[e_loc + 1:])

    #    assert s[1] == '.' or s[0] == '-' and s[2] == '.', "Unsupported format"
    sign = ''
    if mantissa[0] == '-':
        sign = '-'
        mantissa = mantissa[1:]

    digitsafter = len(mantissa) - 1     # num digits after the decimal point
    if exp >= digitsafter:
        return sign + mantissa + '0' * (exp - digitsafter) + '.0'
    elif exp <= -1:
        return sign + '0.' + '0' * (-exp - 1) + mantissa
    ip = exp + 1                        # insertion point
    return sign + mantissa[:ip] + '.' + mantissa[ip:]


def get_auth_token():
    logging.info("Init connection: %s" % url)
    keystone = client.Client(username=usr, password=pasw, tenant_name=admin_tenant_name, auth_url=url)
    auth_token = keystone.auth_token
    logging.info("Auth token: %s" % auth_token)
    return auth_token


def get_billable_accounts(token):
    headers = {"X-Auth-Token": "%s" % token, "Content-Type": "application/json"}
    r = requests.get("%s/api/account" % chargeback_url, headers=headers)
    data = r.json()
    logging.info("size=%s" % len(data["accounts"]))
    accounts = []
    for account in data["accounts"]:
	if int(next_account_id)<=int(account["id"]):
            if account["status"] == "ACTIVE" or account["status"] == "SUSPENDED":
	        if int(account["id"]) not in account_black_list:
                    if custom_account_id is None or int(custom_account_id) == int(account["id"]):
                        accounts.append(account)
                        logging.info("Account billable=%s" % account)
    return accounts


def get_billable_account_cycle(token, account_id):
    headers = {"X-Auth-Token": "%s" % token, "Content-Type": "application/json"}
    r = requests.get("%s/api/account/%s/cycle" % (chargeback_url, account_id), headers=headers)
    data = r.json()
    cycles = data["cycles"]
    max_billing_cycle_id = 0
    for cycle in cycles:
        start = cycle["start"]
        end = cycle["end"]
        if invoice_range >= start and invoice_range <= end:
            if cycle["id"] > max_billing_cycle_id:
                max_billing_cycle_id = cycle["id"]
    return max_billing_cycle_id


def get_cycle(token, cycle_id):
    headers = {"X-Auth-Token": "%s" % token, "Content-Type": "application/json"}
    r = requests.get("%s/api/cycle/%s" % (chargeback_url, cycle_id), headers=headers)
    data = r.json()
    return data

def get_projects(token, cycle_id):
    headers = {"X-Auth-Token": "%s" % token, "Content-Type": "application/json"}
    r = requests.get("%s/api/cycle/%s/project" % (chargeback_url, cycle_id), headers=headers)
    data = r.json()
    return data

def get_products(token, project_id):
    headers = {"X-Auth-Token": "%s" % token, "Content-Type": "application/json"}
    r = requests.get("%s/api/project/%s/product" % (chargeback_url, project_id), headers=headers)
    data = r.json()
    return data

def update_account_external_id(token, id, external_id):
    headers = {"X-Auth-Token": "%s" % token, "Content-Type": "application/json"}
    r = requests.get("%s/api/account/%s" % (chargeback_url, id), headers=headers)
    response = r.json()
    response["account"]["externalId"] = external_id
    r = requests.put("%s/api/account/%s" % (chargeback_url, id), headers=headers, data=json.dumps(response))
    data = r.json()
    return data


def consume_account_invoice(token, id, payment, description, transactionId, invoice_url):
    headers = {"X-Auth-Token": "%s" % token, "Content-Type": "application/json"}
    payload = {"transaction": {"amount": payment, "description": description, "transactionId": transactionId,
                               "invoice": invoice_url}}
    r = requests.post("%s/api/account/%s/consume" % (chargeback_url, id), headers=headers, data=json.dumps(payload))
    response = r.json()
    return response


def create_item(product, description, quantity, unitPrice, tax_rate, country):
    if country.upper() in EUROPEAN_COUNTRIES:
	productOrService = "service"
    else:
        productOrService = None
    item = {"description": description,
            "productOrService": productOrService,
            "quantity": quantity,
            "unitNetPrice": round(float(unitPrice),2),
            "unitGrossPrice": round(float(unitPrice),2),
            "unitId": None,
            "productId": None,
            "productName": product,
            "taxEnabled": True,
            "taxRate": tax_rate,
            "incomeTaxDeductionRate": None}
    return item


def create_customer_debitdoor(name, address, country, vat, email, phone):
    logging.info("Creating customer:%s" % name)
    customer = {
        "name": name,
        "address": address,
        "phone": phone,
        "email": email,
        "ciNumber": vat,
        "vatNumber": vat,
        "paymentTermsId": paymentTermsId,
        "countryCode": country,
    }
    headers = {"Content-Type": "application/json"}
    r = requests.post("https://api.debitoor.com/api/v1.0/customers?autonumber=true&token=%s" % debitoor_token,
                      headers=headers,
                      data=json.dumps(customer))
    if r.status_code == 200:
        logging.info("Created customer:%s" % name)
        return r.json()
    else:
        logging.error("Cannot create customer:%s error: %i" % (name,r.status_code))
	r.raise_for_status()
        return {"message": "Cannot create customer", "code": r.status_code, "type": "ERROR", "success": False}


def update_customer_debitdoor(externalId, name, address, country, vat, email, phone):
    headers = {"Content-Type": "application/json"}
    r = requests.get("https://api.debitoor.com/api/v1.0/customers/%s?token=%s" % (externalId, debitoor_token),
                     headers=headers)
    if r.status_code == 200:
        customerTmp = r.json()
        number = customerTmp["number"]
        customer = {
            "name": name,
            "number": number,
            "address": address,
            "phone": phone,
            "email": email,
            "ciNumber": vat,
            "vatNumber": vat,
            "paymentTermsId": paymentTermsId,
            "countryCode": country,
        }
        headers = {"Content-Type": "application/json"}
        r = requests.put("https://api.debitoor.com/api/v1.0/customers/%s?token=%s" % (externalId, debitoor_token),
                         headers=headers,
                         data=json.dumps(customer))
        logging.info("Updated customer:%s" % name)
        return r.json()
    else:
        logging.error("Cannot update customer:%i" % r.status_code)
        return {"message": "Cannot update customer", "code": r.status_code, "type": "ERROR", "success": False}


auth_token = get_auth_token()
billable_accounts = get_billable_accounts(auth_token)
invoice_list = []
for billable_account in billable_accounts:
    billable_cycle_id = get_billable_account_cycle(auth_token, billable_account["id"])
    account_tax_rate = 21
    billable_country="ES"
    if billable_account["accountBilling"] is not None:
        if billable_account["accountBilling"]["country"]!="ES":
            account_tax_rate = 0
            try:
                account_tax_rate = EUROPEAN_VAT[billable_account["accountBilling"]["country"].upper()]
            except:
                pass
	    billable_country=billable_account["accountBilling"]["country"]
    if billable_cycle_id > 0:
        data = get_cycle(auth_token, billable_cycle_id)
	projectsTotal = float(data["cycle"]["projectsTotal"])
        projects = get_projects(auth_token, billable_cycle_id)["projects"]
        multiple_projects = len(projects) > 1
        if len(projects) > 0 and projectsTotal> 0 :
            items = []
            for project in projects:
                tenantName = project["tenant"]["name"]
                zoneName = project["tenant"]["zone"]["name"]
                products = get_products(auth_token, project["id"])["products"]
                for product in products:
                    productDescription = product["productType"]["description"]
                    resources = product["resources"]
                    productBaseFee = product["baseFee"]
                    zone_and_tenant = ""
                    zone_and_tenant = "Zona: " + zoneName + "\n"
                    zone_and_tenant = zone_and_tenant + "Tenant: " + tenantName + "\n"
                    item = create_item(productDescription + " tarifa mensual",
                                       zone_and_tenant, 1, productBaseFee, account_tax_rate, billable_country)
                    if productBaseFee > 0:
                        items.append(item)
                    for resource in resources:
                        resourceDescription = resource["resourceType"]["description"]
                        resourceUnits = str(resource["ammount"])
                        resourceAccumulatedFee = str(resource["accumulatedFee"])
                        resourceUnitFee = str(non_exp_repr(resource["unitFee"]))
                        resourceFixedFee = str(resource["fixedFee"])
			resourceFreeTier = str(resource["freeUnitsPerCycle"])
                        zone_and_tenant = ""
                        zone_and_tenant = "- Zona: " + zoneName + " "
                        zone_and_tenant = zone_and_tenant + " Tenant: " + tenantName + "\n"
			if product["productType"]["id"] not in HIDDEN_PRODUCTS:
			    productLine = productDescription + " - " + resourceDescription
			    detailLine = "- Unidades consumidas: " + resourceUnits + "\n"
			    if float(resourceFreeTier)>0.0:
			        detailLine = detailLine + "- Unidades gratuitas: " + resourceFreeTier + "\n"
			    billable = int(resourceUnits) - int(resourceFreeTier)
			    if billable<0:
				billable=0
			    detailLine = detailLine + "- Total unidades facturables: " + str(billable) + "\n"
			    detailLine = detailLine + "- Coste por unidad: " + resourceUnitFee + " EUR\n"
			    if float(resourceFixedFee) > 0.0:
				detailLine = detailLine + "- Coste fijo mensual: " + resourceFixedFee + " EUR\n"
                            item = create_item(productLine, zone_and_tenant + detailLine, 1, resourceAccumulatedFee, account_tax_rate, billable_country)
                            items.append(item)
            externalId = billable_account["externalId"]
            name_ = ""
            address_ = ""
            country_ = "ES"
            taxId_ = ""
            if billable_account["accountBilling"] is not None:
                name_ = billable_account["accountBilling"]["companyName"]
                address_ = billable_account["accountBilling"]["address"] + "\n" + \
                           billable_account["accountBilling"]["zipCode"] + " - " + \
                           billable_account["accountBilling"]["city"] + "\n" + \
                           billable_account["accountBilling"]["state"]
                country_ = billable_account["accountBilling"]["country"]
                taxId_ = billable_account["accountBilling"]["taxId"]
                if len(externalId) == 0:
                    # Create account
                    customer = create_customer_debitdoor(name_,
                                                         address_,
                                                         country_,
                                                         taxId_,
                                                         billable_account["accountBilling"]["contactEmail"],
                                                         billable_account["accountBilling"]["contactPhone"])
                    externalId = customer["id"]
                    id = billable_account["id"]
                    update_account_external_id(auth_token, id, externalId)
                else:
                    # Update account
                    customer = update_customer_debitdoor(externalId,
                                                         name_,
                                                         address_,
                                                         country_,
                                                         taxId_,
                                                         billable_account["accountBilling"]["contactEmail"],
                                                         billable_account["accountBilling"]["contactPhone"])
            else:
                logging.info("No account billing info for:" + billable_account["name"])
                country_ = default_country
                if len(externalId) == 0:
                    # Create account
                    name_ = billable_account["name"]
                    address_ = ""
                    taxId_ = ""
                    customer = create_customer_debitdoor(billable_account["name"],
                                                         "",
                                                         country_,
                                                         "",
                                                         "",
                                                         "")
                    externalId = customer["id"]
                    id = billable_account["id"]
                    update_account_external_id(auth_token, id, externalId)
                else:
                    # Update account
                    name_ = billable_account["name"]
                    customer = update_customer_debitdoor(externalId,
                                                         billable_account["name"],
                                                         "",
                                                         country_,
                                                         "",
                                                         "",
                                                         "")
                externalId = customer["id"]
            
	    invoice = {
                "lines": items,
                "customerId": externalId,
                "notes": None,
                "additionalNotes": None,
                "date": invoice_date,
                "dueDate": invoice_date,
                "priceDisplayType": "net",
                "paymentTermsId": 1,
                "sent": False,
                "viewed": False,
                "customerName": name_,
                "customerAddress": address_,
                "customerCountry": country_,
                "customerVatNumber": taxId_,
                "customerCiNumber": taxId_,
            }

	    # There is always at least a network
            if len(items) > 1:
                headers = {"Content-Type": "application/json"}
                r = requests.post("https://api.debitoor.com/api/v1.0/sales/draftinvoices?token=%s" % debitoor_token,
                                  headers=headers, data=json.dumps(invoice))
                response = r.json()
                invoice_number = "PROFORMA"
                id = response["id"]
                totalNetAmount = response["totalNetAmount"]
                totalGrossAmount = response["totalGrossAmount"]

                if billable_account["accountBilling"] is not None:
                    headers = {"Content-Type": "application/json"}
                    r = requests.post("https://api.debitoor.com/api/v1.0/sales/draftinvoices/%s/book?token=%s" % (id, debitoor_token),
                                  headers=headers, data=json.dumps(invoice))
                    response = r.json()
                    invoice_number = response["number"]
                    headers = {"Content-Type": "application/pdf"}
                    r = requests.get(
                        "https://api.debitoor.com/api/v1.0/sales/invoices/%s/pdf?token=%s" % (id, debitoor_token),
                        headers=headers)
                else:
                    headers = {"Content-Type": "application/pdf"}
                    r = requests.get(
                        "https://api.debitoor.com/api/v1.0/sales/draftinvoices/%s/pdf?token=%s" % (id, debitoor_token),
                        headers=headers)
                invoice_name_ = "%s-%s.pdf" % (id, time.strftime("%Y%m%d"))
                encoded_invoice_name = encode(id) + ".pdf"
                with open(encoded_invoice_name, 'wb') as outfile:
                    outfile.write(r.content)
                    outfile.close()

                invoice_url_ = "%s/%s" % (invoice_site_prefix, encoded_invoice_name)
                invoice_list.append({"invoice_range": invoice_range, "name": billable_account["name"],
                                     "totalNetAmount": totalNetAmount, "id": billable_account["id"],
                                     "totalGrossAmount": totalGrossAmount, "country": country_,
                                     "invoiceId": encoded_invoice_name,
                                     "invoice_number": invoice_number,
                                     "invoice_url": invoice_url_})
                swift_command_ = "swift --os-auth-url=%s --os-region-name=%s --os-username=%s --os-password=%s --os-tenant-id=%s upload %s %s" % (
                    os_auth_url, os_region_name, os_username, os_password, os_tenant_id, os_container,
                    encoded_invoice_name)
                call([swift_command_], shell=True)

                max_debug = max_debug - 1
                if max_debug == 0:
                    sys.exit(1)
            else:
                logging.info("Cannot create invoice because no sales this cycle: %s" % billable_account["name"])
    else:
        logging.warning("No billable account:%s" % billable_account["name"])

with open('invoices-%s.json' % time.strftime("%Y-%m-%d"), 'w') as outfile:
    print json.dump(invoice_list, outfile, sort_keys=True, indent=4, separators=(',', ': '))

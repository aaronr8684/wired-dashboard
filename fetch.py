# get data from repairshopr and generate chart

import requests
import logging
import logging.config
import configparser
import json
from datetime import date, datetime
from ratelimiter import RateLimiter
from ImageCharts import ImageCharts

ONE_MINUTE = 60

# logging.config.fileConfig(fname='wired_dashboard_logging.cfg', disable_existing_loggers=False)
# logging.basicConfig(filename='fetch.log', filemode='w', format='%(name)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S', level=logging.DEBUG)
logging.basicConfig(format='%(name)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create file handler/config for logging
f_handler = logging.FileHandler('fetch.log')
f_handler.setLevel(logging.INFO)
f_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
f_handler.setFormatter(f_format)
logger.addHandler(f_handler)

logger.info("~~~~ STARTING SCRIPT ~~~~")

config = configparser.ConfigParser()
config.read('env/config.ini')

category_totals = {}

categories = config.items('categories')
for key, category in categories:
    logger.debug(f"Adding '{category}' to category_totals")
    category_totals[f"{category}"] = {
                                "paid": 0,
                                "unpaid": 0,
                                "overdue": 0,
                                "percent_of_goal": 0
                                } 

chart_config = config['chart_settings']

chart_type = chart_config['chart_type']

rs_api_url = config['repairshopr']['api_url']
rs_api_key = config['repairshopr']['api_token']


@RateLimiter(max_calls=int(config['repairshopr']['rate_limit']), period=ONE_MINUTE)
def get_api_page(page=1, paid='true', unpaid='false', updated_by=date.today().strftime(u"%Y%m01")):
    logger.debug(f"Calling API: page: {page}, paid: {paid}, updated_by: {updated_by}")
    unpaid = 'true'
    if paid == 'true':
        unpaid = 'false'
    if not updated_by == "all":
        return requests.get(
            rs_api_url + f'invoices?page={page}&paid={paid}&unpaid={unpaid}&since_updated_at={updated_by}',
            headers={'accept': 'application/json','Authorization': rs_api_key}
        )
    
    return requests.get(
        rs_api_url + f'invoices?page={page}&paid={paid}&unpaid={unpaid}',
        headers={'accept': 'application/json','Authorization': rs_api_key}
    )


def get_inv_list(paid='true', unpaid='false'):
    if paid == 'true':
        response = get_api_page()
    else:
        response = get_api_page(paid='false', updated_by='all')
    
    logger.debug(f"Response code: {response.status_code}")
    
    json_response = response.json()

    logger.debug(f"Response metadata: {json_response['meta']}")

    pages = int(json_response['meta']['total_pages'])
    logger.info(f"Total pages available: {pages}")
    invoice_list = json_response['invoices']
    for page in range(2, pages+1):
        if paid == 'true':
            response = get_api_page(page=page)
        else:
            response = get_api_page(page=page, paid='false', updated_by='all')
        
        invoice_list = invoice_list + response.json()['invoices']
        logger.debug(f"Getting page {page} of {pages} with response: {response.status_code} (Total invoices: {len(invoice_list)})")

    return invoice_list


@RateLimiter(max_calls=int(config['repairshopr']['rate_limit']), period=ONE_MINUTE)
def get_inv_details(id=0):
    response = requests.get(
            rs_api_url + f'invoices/{id}',
            headers={'accept': 'application/json','Authorization': rs_api_key}
        )
    
    logger.debug(f"Invoice id: {id} - Response code: {response.status_code}")
    
    json_response = response.json()

    return json_response['invoice']


def add_to_categories(invoice):
    logger.info(f"Invoice # - {invoice['number']}")

    is_paid = invoice['is_paid']
    # logger.debug(f"Is paid? {is_paid} and type {type(is_paid)}")

    overdue = False
    if not is_paid:
        overdue = datetime.strptime(invoice['due_date'], '%Y-%m-%d') < datetime.now()
        # logger.debug(f"Is overdue? {overdue}")

    for line_item in invoice['line_items']:
        logger.debug(f"Bundle ID: {line_item['invoice_bundle_id']} with type: {type(line_item['invoice_bundle_id'])}")
        if line_item['invoice_bundle_id'] is not None:
            line_item_net = (float(line_item['price']) * float(line_item['quantity'])) - float(invoice['hardwarecost'])
            line_item_cat = 'PC Sales: Desktop'
        elif line_item['item'] == "Managed Services":
            line_item_net = (float(line_item['price']) * float(line_item['quantity'])) - (float(line_item['cost']) * float(line_item['quantity']))
            line_item_cat = 'Managed Services'
        else:
            line_item_net = (float(line_item['price']) * float(line_item['quantity'])) - (float(line_item['cost']) * float(line_item['quantity']))
            line_item_cat = line_item['product_category']

        if line_item_cat in category_totals:
            if is_paid:
                category_totals[line_item_cat]['paid'] += line_item_net
            elif overdue:
                category_totals[line_item_cat]['overdue'] += line_item_net
            else:
                category_totals[line_item_cat]['unpaid'] += line_item_net
            logger.info(f"Line item: '{line_item_cat}' added (net: {line_item_net}) with paid: {is_paid} and overdue: {overdue} flags")
        else:
            logger.debug(f"Line item: '{line_item_cat}' is not being tracked. Skipping...")

# current_invoice_list = get_inv_list() + get_inv_list(paid='false')

# for inv in current_invoice_list:
#     add_to_categories(get_inv_details(inv['id']))

# print(category_totals)
testing_category_totals = {'Hardware': {'paid': 177.96, 'unpaid': 307.01, 'overdue': 968.79, 'percent_of_goal': 0}, 'Labor: In-Shop': {'paid': 2239.9799999999996, 'unpaid': 960.0, 'overdue': 289.99, 'percent_of_goal': 0}, 'Labor: On-Site': {'paid': 210.0, 'unpaid': 1290.0, 'overdue': 1670.0, 'percent_of_goal': 0}, 'Labor: Remote': {'paid': 1260.0, 'unpaid': 210.0, 'overdue': 180.0, 'percent_of_goal': 0}, 'Managed Services': {'paid': 925.0, 'unpaid': 6639.0, 'overdue': 3099.0, 'percent_of_goal': 0}, 'PC Sales: Desktop': {'paid': 441.02, 'unpaid': 480.0, 'overdue': 0, 'percent_of_goal': 0}, 'PC Sales: Laptop': {'paid': 0, 'unpaid': 478.24, 'overdue': 0, 'percent_of_goal': 0}}

cat_goals = []

for category in testing_category_totals:
    testing_category_totals[category]['percent_of_goal'] = str(int((float(testing_category_totals[category]['paid']) / float(config[category]['goal']))*100))
    cat_goals.append(testing_category_totals[category]['percent_of_goal'])
    


# print(testing_category_totals)

chart_data = {
    'type':"bar",
    'data':{
        'labels':categories,
        'datasets':[
            {
                'label':'paid',
                'data':cat_goals
            }
        ]
        }
    }
print(categories)

cat_goals_csv = ",".join(cat_goals)
categories_csv = "|".join(testing_category_totals.keys())

print(cat_goals_csv)
print(categories_csv)

ImageCharts().cht('bvs').chs('999x640').chbr('10').chtt('Current Net Income').chds("0,150").chd(f't:{cat_goals_csv}').chdl('paid').chxt('x,y').chxl(f'0:|{categories_csv}').to_file('./static/images/chart.png')

logger.info(f"---- END OF SCRIPT ----")


# get data from repairshopr and generate chart

import requests
import logging
import logging.config
import configparser
import json
import math
from datetime import date, datetime
from ratelimiter import RateLimiter
from ImageCharts import ImageCharts
from urllib.parse import urlencode, quote_plus


ONE_MINUTE = 60

# logging.config.fileConfig(fname='wired_dashboard_logging.cfg', disable_existing_loggers=False)
# logging.basicConfig(filename='fetch.log', filemode='w', format='%(name)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S', level=logging.DEBUG)
logging.basicConfig(format='%(name)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create file handler/config for logging
f_handler = logging.FileHandler('fetch.log')
f_handler.setLevel(logging.DEBUG)
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
                                "paid_w_zero_cost": 0,
                                "unpaid": 0,
                                "overdue": 0,
                                "allow_zero_hw": config[category]['allow_non-zero_costs'] in ('True'),
                                "percent_paid": 0,
                                "percent_paidwzero": 0,
                                "percent_unpaid": 0,
                                "percent_overdue": 0
                                } 


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
    logger.debug(f"Invoice # - {invoice['number']} ({invoice['id']})")

    is_paid = invoice['is_paid']
    # logger.debug(f"Is paid? {is_paid} and type {type(is_paid)}")

    overdue = False
    if not is_paid:
        overdue = datetime.strptime(invoice['due_date'], '%Y-%m-%d') < datetime.now()
        # logger.debug(f"Is overdue? {overdue}")

    for line_item in invoice['line_items']:
        line_item_special = False
        logger.debug(f"Bundle ID: {line_item['invoice_bundle_id']} with type: {type(line_item['invoice_bundle_id'])}")
        if line_item['invoice_bundle_id'] is not None:
            line_item_net = (float(line_item['price']) * float(line_item['quantity'])) - float(invoice['hardwarecost'])
            line_item_cat = 'PC Sales: Desktop'
            line_item_special = True
        elif line_item['item'] == "Managed Services":
            line_item_net = (float(line_item['price']) * float(line_item['quantity'])) - (float(line_item['cost']) * float(line_item['quantity']))
            line_item_cat = 'Managed Services'
        else:
            line_item_net = (float(line_item['price']) * float(line_item['quantity'])) - (float(line_item['cost']) * float(line_item['quantity']))
            line_item_cat = line_item['product_category']

        if line_item_cat in category_totals:
            if is_paid:
                if not category_totals[line_item_cat]['allow_zero_hw'] and ((line_item_special and float(invoice['hardwarecost']) < 0.01) or (not line_item_special and float(line_item['cost']) < 0.01)):
                    category_totals[line_item_cat]['paid_w_zero_cost'] += line_item_net
                    logger.warning(f"Found non-zero cost when non-zero allowed? {category_totals[line_item_cat]['allow_zero_hw']}")
                else:
                    category_totals[line_item_cat]['paid'] += line_item_net
            elif overdue:
                category_totals[line_item_cat]['overdue'] += line_item_net
            else:
                category_totals[line_item_cat]['unpaid'] += line_item_net
            logger.info(f"Line item: '{line_item_cat}' added (net: {line_item_net}) with paid: {is_paid} and overdue: {overdue} flags")
        else:
            logger.debug(f"Line item: '{line_item_cat}' is not being tracked. Skipping...")


def rounduptobase(x, base=10):
    return base * math.ceil(x/base)


# current_invoice_list = get_inv_list() + get_inv_list(paid='false')

# for inv in current_invoice_list:
#     add_to_categories(get_inv_details(inv['id']))

# logger.debug(category_totals)

# Using this for testing code below without grabbing new data
category_totals = {'Hardware': {'paid': 177.96, 'paid_w_zero_cost': 0, 'unpaid': 307.01, 'overdue': 968.79, 'allow_zero_hw': False, 'percent_paid': 0, 'percent_paidwzero': 0, 'percent_unpaid': 0, 'percent_overdue': 0}, 'Labor: In-Shop': {'paid': 2239.9799999999996, 'paid_w_zero_cost': 0, 'unpaid': 960.0, 'overdue': 289.99, 'allow_zero_hw': True, 'percent_paid': 0, 'percent_paidwzero': 0, 'percent_unpaid': 0, 'percent_overdue': 0}, 'Labor: On-Site': {'paid': 210.0, 'paid_w_zero_cost': 0, 'unpaid': 1290.0, 'overdue': 1670.0, 'allow_zero_hw': True, 'percent_paid': 0, 'percent_paidwzero': 0, 'percent_unpaid': 0, 'percent_overdue': 0}, 'Labor: Remote': {'paid': 1260.0, 'paid_w_zero_cost': 0, 'unpaid': 210.0, 'overdue': 180.0, 'allow_zero_hw': True, 'percent_paid': 0, 'percent_paidwzero': 0, 'percent_unpaid': 0, 'percent_overdue': 0}, 'Managed Services': {'paid': 0, 'paid_w_zero_cost': 925.0, 'unpaid': 6639.0, 'overdue': 3099.0, 'allow_zero_hw': False, 'percent_paid': 0, 'percent_paidwzero': 0, 'percent_unpaid': 0, 'percent_overdue': 0}, 'PC Sales: Desktop': {'paid': 441.02, 'paid_w_zero_cost': 0, 'unpaid': 480.0, 'overdue': 0, 'allow_zero_hw': False, 'percent_paid': 0, 'percent_paidwzero': 0, 'percent_unpaid': 0, 'percent_overdue': 0}, 'PC Sales: Laptop': {'paid': 0, 'paid_w_zero_cost': 0, 'unpaid': 478.24, 'overdue': 0, 'allow_zero_hw': False, 'percent_paid': 0, 'percent_paidwzero': 0, 'percent_unpaid': 0, 'percent_overdue': 0}}

chart_colors = f"{config['chart_settings']['paid_color']},{config['chart_settings']['paidzero_color']},{config['chart_settings']['unpaid_color']},{config['chart_settings']['overdue_color']}"

cat_percent_lists = [[],[],[],[]]
max_cat_percent = 0
for category in category_totals:
    temp_cat_percent = 0
    cat_goal = float(config[category]['goal'])
    category_totals[category]['percent_paid'] = str(int((float(category_totals[category]['paid']) / cat_goal)*100))
    category_totals[category]['percent_paidwzero'] = str(int((float(category_totals[category]['paid_w_zero_cost']) / cat_goal)*100))
    category_totals[category]['percent_unpaid'] = str(int((float(category_totals[category]['unpaid']) / cat_goal)*100))
    category_totals[category]['percent_overdue'] = str(int((float(category_totals[category]['overdue']) / cat_goal)*100))
    temp_cat_percent += int(category_totals[category]['percent_paid'])
    cat_percent_lists[0].append(category_totals[category]['percent_paid'])
    temp_cat_percent += int(category_totals[category]['percent_paidwzero'])
    cat_percent_lists[1].append(category_totals[category]['percent_paidwzero'])
    temp_cat_percent += int(category_totals[category]['percent_unpaid'])
    cat_percent_lists[2].append(category_totals[category]['percent_unpaid'])
    temp_cat_percent += int(category_totals[category]['percent_overdue'])
    cat_percent_lists[3].append(category_totals[category]['percent_overdue'])
    if temp_cat_percent > max_cat_percent:
        max_cat_percent = temp_cat_percent
        logger.debug(f"New max percent: {max_cat_percent}")

logger.debug(category_totals)

cat_data_csv = []
for count in range(len(cat_percent_lists)):
    cat_data_csv.append(",".join(cat_percent_lists[count]))

categories_csv = "|".join(category_totals.keys())

logger.debug(f"Chart colors: {chart_colors}")
logger.debug(f"Chart data: {cat_data_csv}")
logger.debug(f"Chart labels: {categories_csv}")

# Get chart and save it to a file
ImageCharts().cht('bvs').chs('999x640').chbr('10').chtt('Percent of Goal').chg('0,25').chxr(f'1,0,{rounduptobase(max_cat_percent,20)},20').chf('bg,s,BFBFBF00').chco(chart_colors).chd(f't:{cat_data_csv[0]}|{cat_data_csv[1]}|{cat_data_csv[2]}|{cat_data_csv[3]}').chds(f'a').chdl('paid  |paid with zero cost  |unpaid  |overdue').chdlp('b').chxt('x,y').chxl(f'0:|{categories_csv}').chxs('1N*f0*%').to_file('./static/images/chart.png')

logger.info(f"---- END OF SCRIPT ----")

import argparse
import atexit
import traceback
import sys
import os

import torch.multiprocessing as mp

from mindsdb_native.config import CONFIG

from mindsdb.utilities.config import Config
from mindsdb.interfaces.native.mindsdb import MindsdbNative
from mindsdb.api.http.start import start as start_http
from mindsdb.api.mysql.start import start as start_mysql
from mindsdb.utilities.fs import get_or_create_dir_struct
from mindsdb.interfaces.database.database import DatabaseWrapper


def close_api_gracefully(p_arr):
    for p in p_arr:
        sys.stdout.flush()
        p.terminate()
        p.join()
        sys.stdout.flush()


if __name__ == '__main__':
    mp.freeze_support()

    parser = argparse.ArgumentParser(description='CL argument for mindsdb server')
    parser.add_argument('--api', type=str, default=None)
    parser.add_argument('--config', type=str, default=None)

    args = parser.parse_args()

    config_path = args.config
    if config_path is None:
        config_dir, _, _ = get_or_create_dir_struct()
        config_path = os.path.join(config_dir, 'config.json')

    print(f'Using configuration file: {config_path}')
    config = Config(config_path)

    CONFIG.MINDSDB_STORAGE_PATH = config['interface']['mindsdb_native']['storage_dir']

    if args.api is None:
        api_arr = [api for api in config['api']]
    else:
        api_arr = args.api.split(',')

    start_functions = {
        'http': start_http,
        'mysql': start_mysql
    }

    mdb = MindsdbNative(config)
    # @TODO Maybe just use `get_model_data` directly here ? Seems like a useless abstraction
    model_data_arr = [
        {
            'name': x['name'],
            'predict': x['predict'],
            'data_analysis': mdb.get_model_data(x['name'])['data_analysis_v2']
        } for x in mdb.get_models()
    ]
    dbw = DatabaseWrapper(config)
    dbw.register_predictors(model_data_arr)

    for broken_name in [name for name, connected in dbw.check_connections().items() if connected is False]:
        print(f'Error failed to integrate with database aliased: {broken_name}')

    p_arr = []
    ctx = mp.get_context('spawn')
    for api in api_arr:
        print(f'Starting Mindsdb {api} API !')
        try:
            p = ctx.Process(target=start_functions[api], args=(config_path, True,))
            p.start()
            p_arr.append(p)
            print(f'Started Mindsdb {api} API !')
        except Exception as e:
            close_api_gracefully(p_arr)
            print(f'Failed to start {api} API with exception {e}')
            print(traceback.format_exc())
            raise

    atexit.register(close_api_gracefully, p_arr=p_arr)

    for p in p_arr:
        p.join()

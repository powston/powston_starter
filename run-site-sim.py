import os
from aemo_to_tariff import spot_to_tariff
from powston_simulator.utils import plot, read_vars_from_script, run_scripted_simulation, find_battery_loss
from powston_simulator.sim_utils import (get_active_user_code, save_user_code, get_meter_inverter_data,
                       site_info, get_inverter_params, set_battery_loss, check_local_paths)
try:
    from inverterintelligence.user_actions import replace_variables
    from inverterintelligence.ii_logging import logger
except ImportError:
    from powston_simulator.fallback import replace_variables, logger
from powston_simulator.sim_utils import test_cicd_actions
import json
from datetime import datetime
from matplotlib import pyplot
import numpy as np
import imageio
import io
from scipy.optimize import differential_evolution
import argparse

def get_args():
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--inverter_id', type=int, default=2051, help='Inverter ID')
    parser.add_argument('--days_ago', type=int, default=7, help='Days ago to get data from')
    parser.add_argument('--days', type=int, default=7, help='Days ago to get data from')
    parser.add_argument('--fast', type=int, default=7, help='Top impact variables')
    parser.add_argument('--battery_loss', type=int, default=40, help='Battery loss percentage')
    args = parser.parse_args()
    return args


def main():
    args = get_args()
    inverter_id = args.inverter_id
    battery_loss = args.battery_loss
    days_ago = args.days_ago
    top_fast = args.fast
    days = args.days
    check_local_paths()
    sim_inverter(inverter_id, battery_loss=battery_loss, days_ago=days_ago, days=days, top_fast=top_fast)

def sim_inverter(
    inverter_id, battery_loss=40, days_ago=7, days=7, top_fast=7,
    file_save_directory='./sims'
):
    os.makedirs(file_save_directory, exist_ok=True)
    started_at = datetime.now().isoformat()
    _, site_id, rule_name, inverter_code, last_training_impact = get_active_user_code(inverter_id)
    tune_variables = None
    if top_fast == 3:
        tune_variables = ["BATTERY_SOC_NEEDED", "GOOD_SUN_DAY", "ALWAYS_IMPORT_SOC"][:top_fast]
    if 'PowstonAutoTuned' not in str(rule_name):
        logger.info(f"Rule name {rule_name} does not contain 'PowstonAutoTuned': skipping.")
        return

    output_file = os.path.join(file_save_directory, f"{site_id}.json")

    file_name = save_user_code(inverter_id, inverter_code['user_code'])
    
    # get the inverter data
    meter_data_df, interval = get_meter_inverter_data(inverter_id, days_ago=days_ago, days=days)
    if meter_data_df is None or meter_data_df.shape == (0, 0):
        logger.info(f"No data available for inverter {inverter_id}: skipping simulation.")
        return
    start_date = meter_data_df.index.min().strftime('%Y-%m-%d')
    end_date = meter_data_df.index.max().strftime('%Y-%m-%d')
    network, tariff, export_tariff, daily_fee, latitude, longitude, state, timezone_str = site_info(site_id)

    export_limit_max, installed_battery, installed_solar, inverter_power, timezone, latitude, longitude, battery_capacity, charge_rate, max_ppv_power, battery_loss = get_inverter_params(inverter_id)  # noqa: E501
    daily_fee = max(daily_fee, meter_data_df['billed_fixed_costs'].sum() / days)
    battery_charge = meter_data_df['start_battery_soc'].iloc[0] * battery_capacity / 100.0
    grid_limit = charge_rate * 1.5
    if battery_loss is None:
        best_battery_loss = find_battery_loss(
            meter_data_df, file_name, interval,
            battery_capacity, tariff, export_tariff, network,
            charge_rate, max_ppv_power, daily_fee,
            spot_to_tariff, state, grid_limit,
            latitude, longitude, timezone, battery_charge
        )
        set_battery_loss(inverter_id, best_battery_loss)
        battery_loss = best_battery_loss
    meter_data_df['forecast'] = meter_data_df['forecasts']
    meter_data_df['export_limit_max'] = export_limit_max
    meter_data_df['feed_in_power_limitation'] = meter_data_df['inverter_params'].apply(
        lambda x: json.loads(x).get('feed_in_power_limitation', export_limit_max) if x else export_limit_max)

    logger.debug(f'self.network {tariff} {network} bat {installed_battery} {installed_solar} {inverter_power} {timezone} {latitude} {longitude}')
    idx = meter_data_df['start_battery_soc'].first_valid_index()
    start_soc = meter_data_df.loc[idx, 'start_battery_soc'] if idx is not None else None
    lines = []
    with open(file_name, "r") as file:
        script_content = file.read()
    script_bill, ret_df = run_scripted_simulation(
        meter_data_df, script_content, file_name, interval=interval,
        battery_capacity=battery_capacity, tariff=tariff, export_tariff=export_tariff, network=network,
        charge_rate=charge_rate, max_ppv_power=max_ppv_power, daily_fee=daily_fee,
        spot_to_tariff=spot_to_tariff, state=state, battery_loss=battery_loss,
        latitude=latitude, longitude=longitude, timezone_str=timezone,
        battery_charge=battery_charge, grid_limit=grid_limit)
    plot(ret_df)

    # Convert the ret_df to an array of dictionaries with
    # interval_time: string
    # spot_price: number
    # battery_soc: number
    # cost: number

    ret_df['sim_bill'] = ret_df['sim_cost'].cumsum()
    iteration = {
        'config': read_vars_from_script(file_name),
        'final_bill': script_bill,
        'simulation': ret_df[['interval_time', 'buy_price', 'sell_price', 'battery_soc',
                              'sim_cost', 'sim_bill']].assign(interval_time=lambda df: df['interval_time'].dt.strftime('%Y-%m-%dT%H:%M:%S%z')).to_dict(orient='records')
    }
    sim_dict = {
        'inverter_id': inverter_id,
        'site_id': site_id,
        'iterations': [iteration],
        'best': iteration,
        'best_bill': script_bill,
    }
    with open(output_file, 'w') as f:
        json.dump(sim_dict, f)

    logger.info(f"Script {file_name} bill: {script_bill}")

    x = np.linspace(0, 2 * np.pi, 100)
    images = []

    with open(file_name, "r") as file:
        script_content = file.read()
    lines = []
    var_dict = read_vars_from_script(file_name)
    var_names = list(var_dict.keys())
    logger.info(f"Tuning variables: {var_names}")
    bounds = [(0, 100) for _ in var_names]
    popsize = 5  # tune as you like
    num_params = len(var_names)
    initial_population = np.zeros((popsize * num_params, num_params))

    script_content = ""
    meter_bill, ret_df = run_scripted_simulation(meter_data_df, script_content, "meter.py", interval=interval,
                                                 battery_capacity=battery_capacity, tariff=tariff, network=network,
                                                 charge_rate=charge_rate, max_ppv_power=max_ppv_power, daily_fee=daily_fee,
                                                 spot_to_tariff=spot_to_tariff, state=state, battery_loss=battery_loss,
                                                 latitude=latitude, longitude=longitude, timezone_str=timezone, grid_limit=grid_limit)
    global best_bill

    def set_best_bill(bill):
        global best_bill
        best_bill = bill
    best_bill = script_bill
    logger.info(f"meter bill: {meter_bill}")

    # Set up tune logging
    tune_log_dir = 'tune_logs'
    os.makedirs(tune_log_dir, exist_ok=True)
    tune_log_file = os.path.join(tune_log_dir, f'{inverter_id}_{started_at.replace(":", "-")}.jsonl')
    eval_count = [0]
    baseline_vars = dict(var_dict)

    def objective_function(x, var_names, script_content):
        """
        Converts array 'x' into a dictionary of {variable_name: value},
        sets these in the simulator, runs the simulation,
        and returns the resulting bill (to be minimized).
        """
        global best_bill
        test_vars = dict(zip(var_names, x))

        x_rounded = np.round(x)

        script_content = replace_variables(
            script_content=script_content, new_vars=var_dict,
            old_vars=test_vars, allowed_variables=tune_variables
        )
        with open(f'/tmp/t_user_code_{inverter_id}.py', "w") as file:
            file.write(script_content)

        sim_bill, ret_df = run_scripted_simulation(meter_data_df, script_content, file_name, interval=interval,
                                                   battery_capacity=battery_capacity, tariff=tariff, network=network,
                                                   charge_rate=charge_rate, max_ppv_power=max_ppv_power, daily_fee=daily_fee,
                                                   spot_to_tariff=spot_to_tariff, state=state, battery_loss=battery_loss,
                                                   latitude=latitude, longitude=longitude, timezone_str=timezone, grid_limit=grid_limit)

        # Log every evaluation to tune_logs
        eval_count[0] += 1
        deltas = {k: round(test_vars[k] - baseline_vars.get(k, 0), 2) for k in var_names}
        tune_entry = {
            'eval': eval_count[0],
            'timestamp': datetime.now().isoformat(),
            'inverter_id': inverter_id,
            'site_id': site_id,
            'network': network,
            'battery_capacity': battery_capacity,
            'battery_loss': battery_loss,
            'variables': {k: round(v, 2) for k, v in test_vars.items()},
            'deltas_from_baseline': deltas,
            'bill': sim_bill,
            'bill_delta_from_baseline': round(sim_bill - script_bill, 2),
            'bill_delta_from_best': round(sim_bill - best_bill, 2),
            'is_improvement': bool(sim_bill < best_bill),
            'baseline_bill': script_bill,
            'meter_bill': meter_bill,
            'best_bill': best_bill,
        }
        with open(tune_log_file, 'a') as log_f:
            log_f.write(json.dumps(tune_entry) + '\n')

        if sim_bill < best_bill:
            if test_cicd_actions(user_code={'user_code': script_content, 'inverter_id': inverter_code['id']}):
                logger.info(f"New best bill: {sim_bill}")
                if abs(best_bill - sim_bill) < 1:
                    close_enough = True
                best_bill = sim_bill
                set_best_bill(sim_bill)
                best_file_name = f'/tmp/b_user_code_{inverter_id}.py'
                with open(best_file_name, "w") as file:
                    file.write(script_content)
                fig, ax = plot(ret_df)
                buf = io.BytesIO()
                pyplot.savefig(buf, format='png')
                buf.seek(0)
                images.append(imageio.v2.imread(buf))
                imageio.mimsave(best_file_name.replace('.py', '.gif'), images, duration=0.5)
                pyplot.close(fig)
                simulator_file = os.path.join(file_save_directory, f"{site_id}.json")
                sim_dict = {}
                with open(simulator_file, 'r') as f:
                    sim_dict = json.load(f)
                ret_df['sim_bill'] = ret_df['sim_cost'].cumsum()
                iteration = {
                    'config': test_vars,
                    'final_bill': sim_bill,
                    'simulation': ret_df[['interval_time', 'buy_price', 'sell_price', 'battery_soc',
                                        'sim_cost', 'sim_bill']].assign(interval_time=lambda df: df['interval_time'].dt.strftime('%Y-%m-%dT%H:%M:%S%z')).to_dict(orient='records')
                }
                sim_dict['best'] = iteration
                sim_dict['iterations'].append(iteration)
                sim_dict['best_bill'] = sim_bill
                with open(simulator_file, 'w') as f:
                    json.dump(sim_dict, f)

                if len(sim_dict['iterations']) > 1:
                    finished_at = datetime.now().isoformat()
                    training_impact = generate_training_report(meter_bill, sim_bill, test_vars, started_at=started_at, finished_at=finished_at,
                                                            user_code_id=inverter_code['id'], inverter_id=inverter_id,
                                                            start_date=start_date, end_date=end_date)
                    save_best_script(inverter_id, rule_name, inverter_code, training_impact=training_impact, sim_dict=sim_dict)

                logger.info(f"Updated simulation with new best bill: {sim_bill}")

        return sim_bill

    script_content = "action = 'auto'\nreason = 'default: auto'\n"
    lines = []
    with open(file_name, "r") as file:
        script_content = file.read()
    var_dict = read_vars_from_script(file_name)
    var_names = list(var_dict.keys())
    bounds = [(0, 100) for _ in var_names]
    baseline = [var_dict[name] for name in var_names]

    for i in range(popsize * num_params):
        # example offset is up to ±5 from baseline
        offsets = np.random.randint(-5, 6, size=num_params)  # from -5 to +5
        candidate = np.array(baseline) + offsets

        # Clip to bounds so we don't exceed min or max
        for j in range(num_params):
            low, high = bounds[j]
            candidate[j] = np.clip(candidate[j], low, high)

        initial_population[i] = candidate

    # 4) Run differential_evolution to find the best parameters
    result = differential_evolution(
        objective_function,
        bounds=bounds,
        args=(var_names, script_content),
        init=initial_population,
        strategy='best1bin',
        popsize=1,  # we already provide a custom population
        maxiter=100,
        polish=False
    )

    # 5) Retrieve and round final solution
    best_solution = dict(zip(var_names, np.round(result.x)))
    finished_at = datetime.now().isoformat()
    logger.info(f"Best Solution Found ({len(sim_dict['iterations'])}): https://app.powston.com/rules?inverter_id={inverter_id}")
    training_impact = generate_training_report(meter_bill, result.fun, best_solution, started_at=started_at, finished_at=finished_at,
                                               user_code_id=inverter_code['id'], inverter_id=inverter_id,
                                               start_date=start_date, end_date=end_date)
    logger.info(f"Estimated Bill: {result.fun}")

    # Save the sims
    if images:
        imageio.mimsave(os.path.join(file_save_directory, 'b_' + os.path.basename(file_name).replace('.py', '.gif')), images, duration=0.5)
    
    save_best_script(inverter_id, rule_name, inverter_code, training_impact=training_impact, sim_dict=sim_dict)

def generate_training_report(meter_bill, bill, best_solution, started_at, finished_at,
                             user_code_id, inverter_id, start_date, end_date):
    training_impact = {'meter_bill': meter_bill, 'bill': bill,
                       'user_code_id': user_code_id,
                       'inverter_id': inverter_id,
                       'start_date': start_date,
                       'end_date': end_date,
                       'started_at': started_at,
                       'finished_at': finished_at,
                       'code_variables': {}}
    for k, v in best_solution.items():
        # Only upper case
        if k == k.upper():
            logger.info(f"{k} = {int(round(v))}")
            training_impact['code_variables'][k] = int(round(v))
    return training_impact

def save_best_script(inverter_id, rule_name, inverter_code, training_impact, sim_dict):
    if rule_name.startswith('PowstonAutoTuned'):
        # Save the best script back to the server
        best_script = ""
        file_name = f'user_code_{inverter_id}.py'
        # Touch file to ensure it exists
        open(f'/tmp/b_{file_name}', "a").close()
        with open(f'/tmp/b_{file_name}', "r") as file:
            best_script = file.read()
        simulation_finished = False
        if len(sim_dict['iterations']) > 5:
            simulation_finished = True
        if simulation_finished:
            logger.info(f"Simulation finished for inverter {inverter_id}. Saving best script with bill {training_impact['bill']} and training impact: {training_impact['code_variables']}")
        else:
            logger.info(f"Current best script for inverter {inverter_id} with bill {training_impact['bill']} and training impact: {training_impact['code_variables']}")

if __name__ == "__main__":
    main()

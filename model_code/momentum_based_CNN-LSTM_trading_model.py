import pandas as pd
import numpy as np
import os
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Conv1D, MaxPooling1D, LSTM, Dense, Dropout
from sklearn.preprocessing import MinMaxScaler
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import logging
from pathlib import Path

# --- Configuration ---
STOCK_UNIVERSE = [
    'NVDA', 'AMCR', 'LCID', 'F', 'TSLA', 'WBD', 'AAPL', 'SOFI',
    'PLTR', 'AMD', 'GOOGL', 'AMZN', 'OSCR', 'VALE'
]
home_dir = Path.home()
DATA_DIR = home_dir / 'Downloads' / 'stock_market_data'

# Trading & Model parameters
PORTFOLIO_SIZE = 3
TAKE_PROFIT_PCT = 0.005  # Based on nominal price movement from actual (slipped) buy price
STOP_LOSS_PCT = 0.01    # Based on nominal price movement from actual (slipped) buy price
MAX_HOLD_DAYS = 3
LOOKBACK_DAYS = 20
PREDICT_HORIZON = 1
TRAINING_YEARS = 2
TRANSACTION_COST_PCT = 0.0005  # 0.05% of transaction value (e.g., 0.0005 for 0.05%)
SLIPPAGE_PCT = 0.0005          # 0.05% adverse price movement on execution (e.g., 0.0005 for 0.05%)

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler()])

# === MODULE 1: DATA LOADING & FEATURE ENGINEERING (MODIFIED & FIXED) ===
def create_feature_dataset_from_local(ticker, start_date, end_date):
    filepath = os.path.join(DATA_DIR, f"{ticker}.csv")
    try:
        with open(filepath, 'r') as f:
            first_line = f.readline()
        if 'Price,Close,High' in first_line:
            logging.warning(f"Detected malformed CSV header for {ticker}. Adjusting parser.")
            column_names = ['Date', 'Close', 'High', 'Low', 'Open', 'Volume']
            data = pd.read_csv(
                filepath, header=None, names=column_names, skiprows=3,
                index_col='Date', parse_dates=True
            )
        else:
            data = pd.read_csv(filepath, index_col='Date', parse_dates=True)

        data = data.loc[str(start_date):str(end_date)].copy()
        if data.empty:
            logging.warning(f"No data for {ticker} in local file for range {start_date} to {end_date}")
            return None, None

        data['SMA_9'] = data['Close'].rolling(window=9).mean()
        data['SMA_21'] = data['Close'].rolling(window=21).mean()
        data['Close'] = pd.to_numeric(data['Close'], errors='coerce')
        data['RSI_14'] = data['Close'].rolling(14).apply(
            lambda x: pd.Series(x).diff().fillna(0).apply(lambda y: y if y > 0 else 0).sum() / pd.Series(x).diff().fillna(0).abs().sum() * 100 if pd.Series(x).diff().fillna(0).abs().sum() != 0 else 50,
            raw=False
        )
        data['Future_Change'] = data['Close'].shift(-PREDICT_HORIZON) / data['Close'] - 1
        data.dropna(inplace=True)
        data.reset_index(inplace=True)
        feature_columns = ['Open', 'High', 'Low', 'Close', 'Volume', 'SMA_9', 'SMA_21', 'RSI_14']
        return data, feature_columns
    except FileNotFoundError:
        logging.error(f"Local data file not found for {ticker} at {filepath}. Please run the downloader script.")
        return None, None
    except Exception as e:
        logging.error(f"Error processing local file for {ticker}: {e}")
        return None, None

# === MODULE 2: MODEL TRAINING ===
def train_model_for_backtest(training_start_date, training_end_date):
    logging.info(f"Starting model training from local data: {training_start_date} to {training_end_date}")
    all_X_train, all_y_train, n_features = [], [], 0
    for ticker in STOCK_UNIVERSE:
        logging.info(f"  Loading training data for {ticker}...")
        stock_data, feature_cols = create_feature_dataset_from_local(ticker, training_start_date, training_end_date)
        if stock_data is None or stock_data.empty:
            logging.warning(f"  No training data for {ticker} in the specified range.")
            continue
        if not feature_cols:
             logging.warning(f"  No feature columns for {ticker}.")
             continue
        if not n_features: n_features = len(feature_cols)
        for col in feature_cols:
            stock_data[col] = pd.to_numeric(stock_data[col], errors='coerce')
        stock_data.dropna(subset=feature_cols, inplace=True)
        if stock_data.empty:
            logging.warning(f"  Data for {ticker} became empty after ensuring numeric features.")
            continue
        scaler = MinMaxScaler(feature_range=(0, 1))
        features_scaled = scaler.fit_transform(stock_data[feature_cols])
        for i in range(LOOKBACK_DAYS, len(features_scaled)):
            all_X_train.append(features_scaled[i-LOOKBACK_DAYS:i])
            all_y_train.append(stock_data['Future_Change'].iloc[i])

    if not all_X_train:
        logging.error("Could not generate any training data. Exiting.")
        return None
    X_train, y_train = np.array(all_X_train), np.array(all_y_train)
    if X_train.shape[2] != n_features:
        logging.warning(f"Mismatch in n_features. Expected: {n_features}, Got: {X_train.shape[2]}. Adjusting n_features.")
        n_features = X_train.shape[2]

    logging.info(f"Total training samples: {X_train.shape[0]}. Features per timestep: {n_features}")
    model = Sequential([
        Conv1D(filters=64, kernel_size=3, activation='relu', input_shape=(LOOKBACK_DAYS, n_features)),
        MaxPooling1D(pool_size=2), LSTM(units=100, return_sequences=True, activation='relu'),
        Dropout(0.3), LSTM(units=80, activation='relu'), Dropout(0.3),
        Dense(units=50, activation='relu'), Dense(units=1)
    ])
    model.compile(optimizer='adam', loss='mean_squared_error')
    model.summary(print_fn=logging.info)
    logging.info("Training the unified model...")
    model.fit(X_train, y_train, epochs=40, batch_size=64, validation_split=0.1, verbose=1)
    logging.info("Model training complete.")
    return model

# === MODULE 3: BACKTESTING ENGINE (WITH TRANSACTION COSTS & SLIPPAGE) ===
def run_backtest(model, backtest_start_date, backtest_end_date):
    logging.info(f"--- Starting Backtest from {backtest_start_date.date()} to {backtest_end_date.date()} (Costs: Txn={TRANSACTION_COST_PCT*100:.3f}%, Slip={SLIPPAGE_PCT*100:.3f}%) ---")
    backtest_dates = pd.to_datetime(pd.date_range(start=backtest_start_date, end=backtest_end_date, freq='B'))

    if backtest_dates.empty:
        logging.warning("No business dates found in the backtesting period. Exiting backtest.")
        return [], pd.Series([100000.0], index=[backtest_start_date]), 0.0

    initial_capital = 100000.0
    cash = initial_capital
    portfolio = {}  # ticker -> {'buy_price_actual_execution': float, 'buy_date': datetime, 'qty': float, 'last_eval_price': float}
    trade_log = []
    total_transaction_costs_paid = 0.0
    
    daily_equity_log = []
    processed_trading_dates = []

    logging.info("Pre-loading all backtesting data from local files...")
    all_stock_data = {}
    feature_cols_ref = []
    for ticker in STOCK_UNIVERSE:
        filepath = os.path.join(DATA_DIR, f"{ticker}.csv")
        df_temp = None
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f: first_line = f.readline()
                if 'Price,Close,High' in first_line:
                    column_names = ['Date', 'Close', 'High', 'Low', 'Open', 'Volume']
                    df_temp = pd.read_csv(filepath, header=None, names=column_names, skiprows=3, index_col='Date', parse_dates=True)
                else:
                    df_temp = pd.read_csv(filepath, index_col='Date', parse_dates=True)
                df_temp.columns = df_temp.columns.str.capitalize()
                required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
                for col in required_cols:
                    if col not in df_temp.columns: df_temp = None; break
                    df_temp[col] = pd.to_numeric(df_temp[col], errors='coerce')
                if df_temp is None: continue
                df_temp.dropna(subset=required_cols, inplace=True)
                if df_temp.empty: continue
                df_temp['SMA_9'] = df_temp['Close'].rolling(window=9).mean()
                df_temp['SMA_21'] = df_temp['Close'].rolling(window=21).mean()
                df_temp['RSI_14'] = df_temp['Close'].rolling(14).apply(
                    lambda x: pd.Series(x).diff().fillna(0).apply(lambda y: y if y > 0 else 0).sum() / pd.Series(x).diff().fillna(0).abs().sum() * 100 if pd.Series(x).diff().fillna(0).abs().sum() != 0 else 50, raw=False)
                current_feature_cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume', 'SMA_9', 'SMA_21', 'RSI_14'] if c in df_temp.columns]
                if not feature_cols_ref: feature_cols_ref = current_feature_cols
                df_temp = df_temp[feature_cols_ref + [col for col in df_temp.columns if col not in feature_cols_ref and col in required_cols]]
                df_temp.dropna(subset=feature_cols_ref, inplace=True)
                all_stock_data[ticker] = df_temp
            except Exception as e: logging.error(f"Error pre-loading data for {ticker}: {e}")
        else: logging.warning(f"Data file not found for {ticker} at {filepath} during pre-loading.")

    if not all_stock_data or not feature_cols_ref:
        logging.error("Insufficient data or feature columns for backtest after pre-loading. Exiting.")
        return [], pd.Series([initial_capital], index=[backtest_start_date]), 0.0

    for today in backtest_dates:
        logging.debug(f"--- Processing Day: {today.date()} ---")
        if not any(ticker in all_stock_data and today in all_stock_data[ticker].index for ticker in STOCK_UNIVERSE):
            logging.info(f"No market data for any stock on {today.date()}. Carrying equity forward.")
            if processed_trading_dates: daily_equity_log.append(daily_equity_log[-1])
            elif not daily_equity_log: daily_equity_log.append(initial_capital)
            processed_trading_dates.append(today)
            continue

        # --- Process Sells ---
        for ticker, position in list(portfolio.items()):
            if ticker not in all_stock_data or today not in all_stock_data[ticker].index:
                logging.warning(f"No data for {ticker} on {today.date()} to evaluate sell. Holding.")
                continue

            nominal_sell_price = all_stock_data[ticker].loc[today]['Open']
            if pd.isna(nominal_sell_price):
                logging.warning(f"Nominal Open price for {ticker} on {today.date()} is NaN. Cannot process sell. Holding.")
                continue

            cost_basis_actual_buy_price = position['buy_price_actual_execution']
            days_held = (today - position['buy_date']).days
            
            # TP/SL check is based on nominal market move vs. actual (slipped) buy price
            profit_loss_pct_for_trigger = (nominal_sell_price - cost_basis_actual_buy_price) / cost_basis_actual_buy_price if cost_basis_actual_buy_price != 0 else 0
            reason_to_sell = None

            if profit_loss_pct_for_trigger >= TAKE_PROFIT_PCT: reason_to_sell = "Take Profit"
            elif profit_loss_pct_for_trigger <= -STOP_LOSS_PCT: reason_to_sell = "Stop Loss"
            elif days_held >= MAX_HOLD_DAYS: reason_to_sell = "Time Limit"

            if reason_to_sell:
                # Apply sell-side slippage
                actual_sell_price = nominal_sell_price * (1 - SLIPPAGE_PCT)
                
                gross_sell_value = actual_sell_price * position['qty']
                sell_transaction_cost = gross_sell_value * TRANSACTION_COST_PCT
                net_cash_from_sell = gross_sell_value - sell_transaction_cost
                
                cash += net_cash_from_sell
                total_transaction_costs_paid += sell_transaction_cost

                # P&L of the trade itself (actual sell vs actual buy)
                pnl_value_trade = (actual_sell_price - cost_basis_actual_buy_price) * position['qty']
                pnl_percent_trade = (actual_sell_price - cost_basis_actual_buy_price) / cost_basis_actual_buy_price if cost_basis_actual_buy_price != 0 else 0
                
                logging.info(
                    f"SELLING {position['qty']:.0f} {ticker} at nominal ${nominal_sell_price:.2f} (actual exec ${actual_sell_price:.2f}). "
                    f"Reason: {reason_to_sell}. Trade P/L: {pnl_percent_trade:.2%} (${pnl_value_trade:.2f}). "
                    f"Sell Txn Cost: ${sell_transaction_cost:.2f}. Cash: ${cash:.2f}"
                )
                trade_log.append({
                    'Date': today, 'Ticker': ticker, 'Action': 'Sell',
                    'Nominal_Price': nominal_sell_price,
                    'Actual_Exec_Price': actual_sell_price,
                    'Quantity': position['qty'],
                    'PnL_Percent_Trade': pnl_percent_trade, # P&L from actual buy (slipped) to actual sell (slipped)
                    'PnL_Value_Trade': pnl_value_trade,     # P&L from actual buy (slipped) to actual sell (slipped)
                    'Transaction_Cost': sell_transaction_cost,
                    'Original_Buy_Price_Actual_Exec': cost_basis_actual_buy_price
                })
                del portfolio[ticker]
        
        # --- Process Buys ---
        target_investment_per_stock = initial_capital / PORTFOLIO_SIZE # Or current cash / PORTFOLIO_SIZE for dynamic sizing
        slots_to_fill = PORTFOLIO_SIZE - len(portfolio)

        if slots_to_fill > 0:
            predictions = []
            model_input_feature_cols = feature_cols_ref
            candidate_tickers = [t for t in STOCK_UNIVERSE if t not in portfolio and t in all_stock_data]

            for ticker in candidate_tickers:
                data_for_prediction = all_stock_data[ticker].loc[:today - pd.Timedelta(days=1)]
                if len(data_for_prediction) < LOOKBACK_DAYS: continue
                data_slice = data_for_prediction.tail(LOOKBACK_DAYS)[model_input_feature_cols].copy()
                data_slice.dropna(inplace=True)
                if len(data_slice) < LOOKBACK_DAYS: continue
                scaler = MinMaxScaler(feature_range=(0,1))
                scaled_features = scaler.fit_transform(data_slice)
                input_data = np.array([scaled_features])
                if input_data.shape[1] != LOOKBACK_DAYS or input_data.shape[2] != len(model_input_feature_cols):
                    logging.warning(f"Input data shape mismatch for {ticker}: {input_data.shape}. Skipping.")
                    continue
                predicted_change = model.predict(input_data, verbose=0)[0][0]
                predictions.append({'ticker': ticker, 'prediction': predicted_change})
            
            predictions.sort(key=lambda x: x['prediction'], reverse=True)

            for i in range(min(slots_to_fill, len(predictions))):
                top_candidate = predictions[i]['ticker']
                if today not in all_stock_data[top_candidate].index:
                    logging.warning(f"Data for {top_candidate} not available on {today.date()} for buying. Skipping.")
                    continue
                
                nominal_buy_price = all_stock_data[top_candidate].loc[today]['Open']
                if pd.isna(nominal_buy_price) or nominal_buy_price <= 0:
                    logging.warning(f"Invalid nominal buy price ${nominal_buy_price:.2f} for {top_candidate}. Skipping.")
                    continue

                # Apply buy-side slippage
                actual_buy_price = nominal_buy_price * (1 + SLIPPAGE_PCT)
                
                qty_to_buy = np.floor(target_investment_per_stock / actual_buy_price) # Qty based on actual asset price
                if qty_to_buy <= 0: continue

                gross_cost_of_purchase = qty_to_buy * actual_buy_price
                buy_transaction_cost = gross_cost_of_purchase * TRANSACTION_COST_PCT
                total_cost_of_purchase = gross_cost_of_purchase + buy_transaction_cost

                if cash >= total_cost_of_purchase:
                    cash -= total_cost_of_purchase
                    total_transaction_costs_paid += buy_transaction_cost
                    portfolio[top_candidate] = {
                        'buy_price_actual_execution': actual_buy_price, # Store price after slippage
                        'buy_date': today, 
                        'qty': qty_to_buy, 
                        'last_eval_price': actual_buy_price
                    }
                    trade_log.append({
                        'Date': today, 'Ticker': top_candidate, 'Action': 'Buy', 
                        'Nominal_Price': nominal_buy_price,
                        'Actual_Exec_Price': actual_buy_price,
                        'Quantity': qty_to_buy,
                        'Transaction_Cost': buy_transaction_cost
                    })
                    logging.info(
                        f"BUYING {qty_to_buy:.0f} {top_candidate} at nominal ${nominal_buy_price:.2f} (actual exec ${actual_buy_price:.2f}). "
                        f"Gross Cost: ${gross_cost_of_purchase:.2f}. Buy Txn Cost: ${buy_transaction_cost:.2f}. Cash: ${cash:.2f}"
                    )
                elif qty_to_buy > 0:
                    logging.warning(f"Not enough cash (${cash:.2f}) for {top_candidate} (total cost ${total_cost_of_purchase:.2f}).")

        # --- EOD Portfolio Valuation ---
        current_holdings_value = 0
        for ticker, pos_data in portfolio.items():
            eod_price_nominal = pos_data['last_eval_price'] # Default to last known
            if ticker in all_stock_data and today in all_stock_data[ticker].index:
                current_close = all_stock_data[ticker].loc[today]['Close']
                if not pd.isna(current_close):
                    eod_price_nominal = current_close
                # For valuation, we use the nominal EOD price. Slippage/costs are realized at trade.
            current_holdings_value += pos_data['qty'] * eod_price_nominal
            portfolio[ticker]['last_eval_price'] = eod_price_nominal
        
        total_eod_portfolio_value = cash + current_holdings_value
        daily_equity_log.append(total_eod_portfolio_value)
        processed_trading_dates.append(today)
        if today == backtest_dates[-1] or (today.day % 7 == 0) : # Log less frequently to reduce noise, but always last day
             logging.info(f"EOD {today.date()}: Holdings: ${current_holdings_value:.2f}, Cash: ${cash:.2f}, Equity: ${total_eod_portfolio_value:.2f}")


    logging.info("--- Backtest Finished ---")
    if not processed_trading_dates:
        logging.warning("No trading days processed.")
        return trade_log, pd.Series([initial_capital], index=[backtest_start_date]), total_transaction_costs_paid
        
    equity_curve = pd.Series(daily_equity_log, index=pd.Index(processed_trading_dates, name="Date"))
    return trade_log, equity_curve, total_transaction_costs_paid

# --- MODULE 4: RESULTS ANALYSIS (ADJUSTED FOR NEW EQUITY CURVE & COSTS) ---
def analyze_results(trade_log, portfolio_values_series, total_transaction_costs_paid):
    if portfolio_values_series.empty:
        logging.warning("Portfolio values series is empty. Cannot analyze results.")
        return

    initial_equity = portfolio_values_series.iloc[0]
    final_equity = portfolio_values_series.iloc[-1]
    total_return_on_equity = (final_equity - initial_equity) / initial_equity

    print("\n" + "="*50)
    print("--- Backtest Performance Analysis (with Costs) ---")
    print("="*50)
    if not portfolio_values_series.index.empty:
        start_date_str = portfolio_values_series.index[0].strftime('%Y-%m-%d')
        end_date_str = portfolio_values_series.index[-1].strftime('%Y-%m-%d')
        print(f"Period: {start_date_str} to {end_date_str}")
    else:
        print("Period: Unknown (no dates in portfolio values index)")

    print(f"Initial Portfolio Value: ${initial_equity:,.2f}")
    print(f"Final Portfolio Value:   ${final_equity:,.2f}")
    print(f"Total Return (Equity Curve): {total_return_on_equity:.2%}")
    print(f"Total Transaction Costs Paid: ${total_transaction_costs_paid:,.2f}")
    print("-" * 25)

    if not trade_log:
        logging.warning("No trades were made during the backtest.")
        print("Total Sell Trades: 0")
    else:
        trades_df = pd.DataFrame(trade_log)
        sells_df = trades_df[trades_df['Action'] == 'Sell'].copy()
        if sells_df.empty:
            logging.warning("No sell trades were logged.")
            print("Total Sell Trades: 0")
        else:
            # Ensure PnL columns are numeric
            sells_df['PnL_Percent_Trade'] = pd.to_numeric(sells_df['PnL_Percent_Trade'], errors='coerce')
            sells_df['PnL_Value_Trade'] = pd.to_numeric(sells_df['PnL_Value_Trade'], errors='coerce')
            
            wins = sells_df[sells_df['PnL_Value_Trade'] > 0] # Win if PnL value > 0
            losses = sells_df[sells_df['PnL_Value_Trade'] <= 0] # Loss if PnL value <= 0
            
            total_sell_trades = len(sells_df)
            win_rate = len(wins) / total_sell_trades if total_sell_trades > 0 else 0
            
            avg_profit_pct_trade = wins['PnL_Percent_Trade'].mean() if not wins.empty else 0
            avg_loss_pct_trade = losses['PnL_Percent_Trade'].mean() if not losses.empty else 0
            
            print(f"Total Sell Trades: {total_sell_trades}")
            print(f"Win Rate (based on PnL_Value_Trade > 0): {win_rate:.2%}")
            print(f"Avg Winning Trade (PnL %): {avg_profit_pct_trade:.2%}") # PnL of trade itself
            print(f"Avg Losing Trade (PnL %):  {avg_loss_pct_trade:.2%}")  # PnL of trade itself
            
            if total_sell_trades > 0 :
                avg_pnl_value_trade = sells_df['PnL_Value_Trade'].mean()
                print(f"Average PnL per Sell Trade: ${avg_pnl_value_trade:.2f}")
                total_pnl_from_trades = sells_df['PnL_Value_Trade'].sum()
                print(f"Total PnL from Trades: ${total_pnl_from_trades:.2f}")
                
                sum_win_pnl_val = wins['PnL_Value_Trade'].sum()
                sum_loss_pnl_val = abs(losses['PnL_Value_Trade'].sum())
                profit_factor_val = sum_win_pnl_val / sum_loss_pnl_val if sum_loss_pnl_val != 0 else float('inf')
                print(f"Profit Factor (Sum of Win Values / Sum of Loss Values): {profit_factor_val:.2f}")

                if len(portfolio_values_series) > 1:
                    daily_returns = portfolio_values_series.pct_change().dropna()
                    if len(daily_returns) > 1:
                        sharpe_ratio = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() != 0 else 0
                        print(f"Sharpe Ratio (Annualized, approx.): {sharpe_ratio:.2f}")
    print("="*50 + "\n")
    
    plt.style.use('seaborn-v0_8-darkgrid')
    plt.figure(figsize=(14, 7))
    plt.plot(portfolio_values_series.index, portfolio_values_series.values, label='Strategy Equity Curve (Net of all costs)', color='royalblue')
    plt.title('Portfolio Value Over Time (Including Costs)', fontsize=16)
    plt.xlabel('Date', fontsize=12)
    plt.ylabel('Portfolio Value ($)', fontsize=12)
    plt.legend()
    plt.show()

# === MAIN EXECUTION BLOCK ===
def main():
    backtest_end_date = datetime(2025, 8, 11) # Ensure it's not a weekend if relying on specific end date data
    backtest_start_date = datetime(2025, 6, 13)
    
    training_end_date = backtest_start_date - timedelta(days=1)
    training_start_date = training_end_date - timedelta(days=(TRAINING_YEARS * 365 - 1))

    logging.info(f"Training Period: {training_start_date.date()} to {training_end_date.date()}")
    logging.info(f"Backtesting Period: {backtest_start_date.date()} to {backtest_end_date.date()}")

    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        logging.info(f"Created data directory: {DATA_DIR}")
        logging.warning(f"Please ensure stock CSV files are present in {DATA_DIR}")

    model = train_model_for_backtest(training_start_date, training_end_date)

    if model:
        trade_log, portfolio_values, total_txn_costs = run_backtest(model, backtest_start_date, backtest_end_date)
        analyze_results(trade_log, portfolio_values, total_txn_costs)
    else:
        logging.error("Model training failed. Skipping backtest and analysis.")

if __name__ == "__main__":
    main()
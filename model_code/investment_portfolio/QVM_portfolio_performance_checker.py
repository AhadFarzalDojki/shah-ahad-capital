import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta # For relative date calculations
import traceback # For more detailed error printing

# --- CONFIGURATION ---
DEFAULT_PORTFOLIO_FILE = 'qvm_strategy_trades_from_csv.xlsx'
BENCHMARK_TICKER = '^NDX'  # S&P 500 Index
RISK_FREE_RATE = 0.04301  # Annualized risk-free rate (e.g., 2%) for Sharpe Ratio
TRADING_DAYS_PER_YEAR = 252 # For annualizing metrics

# --- HELPER FUNCTIONS ---

def get_specific_date_input(prompt):
    """Gets a specific date from user input and validates it."""
    while True:
        try:
            date_str = input(prompt + " (YYYY-MM-DD): ")
            dt_obj = datetime.strptime(date_str, '%Y-%m-%d')
            return dt_obj
        except ValueError:
            print("Invalid date format. Please use YYYY-MM-DD.")

def get_evaluation_period():
    """Asks user for the evaluation period, either specific dates or relative."""
    while True:
        choice = input("Define evaluation period by (S)pecific dates or (R)elative to today? [S/R]: ").upper()
        if choice == 'S':
            print("\nEnter specific start and end dates for the evaluation.")
            start_date = get_specific_date_input("Enter performance evaluation start date")
            end_date = get_specific_date_input("Enter performance evaluation end date")
            if start_date >= end_date:
                print("Start date must be before end date. Please try again.")
                continue
            return start_date, end_date
        elif choice == 'R':
            print("\nEnter a relative period from today (e.g., 3m, 6m, 1y, 2y, ytd).")
            period_str = input("Enter relative period (e.g., '3m' for 3 months, '1y' for 1 year, 'ytd' for Year to Date): ").lower()
            
            end_date = datetime.combine(date.today(), datetime.min.time()) # End date is today (midnight for consistency)

            if period_str == 'ytd':
                start_date = datetime(end_date.year, 1, 1)
            else:
                num_str = ""
                unit = ""
                for char in period_str:
                    if char.isdigit():
                        num_str += char
                    else:
                        unit += char
                
                if not num_str or not unit:
                    print("Invalid relative period format. Use a number followed by 'm' or 'y'. E.g., '6m', '1y'.")
                    continue
                
                try:
                    num = int(num_str)
                except ValueError:
                    print(f"Invalid number '{num_str}' in relative period.")
                    continue

                if unit == 'm':
                    start_date = end_date - relativedelta(months=num)
                elif unit == 'y':
                    start_date = end_date - relativedelta(years=num)
                else:
                    print(f"Invalid unit '{unit}'. Use 'm' for months or 'y' for years.")
                    continue
            
            # Ensure start_date is not in the future if end_date is today.
            if start_date > end_date:
                print(f"Calculated start date ({start_date.strftime('%Y-%m-%d')}) is after end date ({end_date.strftime('%Y-%m-%d')}). Adjusting start date to end date.")
                start_date = end_date
            
            print(f"Calculating for period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
            return start_date, end_date
        else:
            print("Invalid choice. Please enter 'S' or 'R'.")


def load_portfolio_from_excel(excel_path):
    """Loads portfolio holdings (Ticker, Shares to Buy, Price at purchase) from the Excel file."""
    try:
        trades_df = pd.read_excel(excel_path, sheet_name='QVM Trades')
        if 'Ticker' not in trades_df.columns or 'Shares to Buy' not in trades_df.columns or 'Price' not in trades_df.columns:
            print("Error: Excel file must contain 'Ticker', 'Shares to Buy', and 'Price' (purchase price) columns.")
            return None, 0
        
        trades_df = trades_df[trades_df['Shares to Buy'] > 0]
        if trades_df.empty:
            print("No stocks with shares to buy found in the portfolio file.")
            return None, 0

        trades_df['Initial Cost'] = trades_df['Shares to Buy'] * trades_df['Price']
        initial_investment = trades_df['Initial Cost'].sum()
        
        print(f"\nPortfolio loaded from '{excel_path}'.")
        print(f"Initial calculated investment from file: ${initial_investment:,.2f}")
        print("Holdings (Ticker, Shares, Purchase Price, Initial Cost):")
        print(trades_df[['Ticker', 'Shares to Buy', 'Price', 'Initial Cost']])
        return trades_df[['Ticker', 'Shares to Buy']], initial_investment
    except FileNotFoundError:
        print(f"Error: Portfolio file '{excel_path}' not found.")
        return None, 0
    except Exception as e:
        print(f"Error loading portfolio from Excel: {e}")
        return None, 0

def fetch_historical_data(tickers, start_date, end_date): # tickers is a list
    """Fetches historical 'Close' prices (auto-adjusted) for given tickers and date range."""
    if start_date >= end_date and end_date.date() != date.today():
        print(f"Warning: Start date ({start_date.strftime('%Y-%m-%d')}) is not before end date ({end_date.strftime('%Y-%m-%d')}). No data will be fetched if end date is not today.")
        if start_date > end_date : return None # Strict check, allow same day for today
        if start_date == end_date and end_date.date() != date.today(): return None


    query_end_date = end_date
    # yfinance's end date is exclusive for the day part if time is 00:00:00.
    # To ensure the specified end_date's data is included, add one day if it's midnight.
    if query_end_date.time() == datetime.min.time() and query_end_date.date() != date.today():
         query_end_date = end_date + timedelta(days=1)
    # If end_date is today, yfinance usually handles it well up to the current data.

    print(f"\nFetching historical data from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} for: {', '.join(tickers) if tickers else 'N/A'}")
    
    try:
        if not tickers:
            print("No tickers provided to fetch historical data.")
            return pd.DataFrame() # Return empty DataFrame, consistent with no data

        # auto_adjust=True: 'Close' column is adjusted for dividends and splits.
        # actions=False: We don't need separate dividend/split columns.
        downloaded_data = yf.download(tickers, start=start_date, end=query_end_date,
                                      auto_adjust=True,
                                      actions=False,
                                      progress=False)
        
        if downloaded_data.empty:
            print("No data fetched from yfinance (downloaded_data is empty). This could be due to invalid tickers, no data for the period, or API issues.")
            return None

        # Extract the 'Close' prices.
        # If multiple tickers (len(tickers) > 1), yf.download usually returns a DataFrame with MultiIndex columns.
        # First level of MultiIndex is 'Open', 'Close', etc. data['Close'] gets DF of close prices.
        # If a single ticker (len(tickers) == 1), yf.download returns a simple DataFrame with 'Open', 'Close', etc. columns.
        # data['Close'] gets a Series.
        data_extracted = None
        if isinstance(downloaded_data.columns, pd.MultiIndex):
            try:
                data_extracted = downloaded_data['Close']
                if data_extracted.empty and not downloaded_data.empty:
                     print("Warning: 'Close' column selection from MultiIndex resulted in an empty DataFrame, though download was not empty.")
            except KeyError:
                print(f"Error: 'Close' data not found in MultiIndex columns. Available price types: {downloaded_data.columns.levels[0]}")
                return None
        else: # Simple DataFrame (usually for a single ticker in the `tickers` list)
            if 'Close' in downloaded_data.columns:
                # For a single ticker, downloaded_data['Close'] is a Series. Convert to DataFrame.
                data_extracted = downloaded_data[['Close']] # Select as DataFrame to preserve column name
                if len(tickers) == 1: # Rename the 'Close' column to the actual ticker name
                    data_extracted = data_extracted.rename(columns={'Close': tickers[0]})
                else: # Should not happen if not MultiIndex and multiple tickers were in request list
                    print("Warning: Data for multiple tickers not in MultiIndex format. Using 'Close' as column name.")
            else:
                print(f"Error: 'Close' column not found in simple DataFrame. Columns: {downloaded_data.columns}")
                return None

        if data_extracted is None or data_extracted.empty:
            print("Price data is empty or could not be extracted after selecting 'Close' column(s).")
            return None
        
        # Filter data to be within the original inclusive start_date and end_date
        # This is important because query_end_date might have been adjusted
        data_filtered = data_extracted[(data_extracted.index >= start_date) & (data_extracted.index <= end_date)]

        if data_filtered.empty:
            print("No data available within the exact specified date range after filtering.")
            return None
            
        # Forward fill missing values, then backfill remaining NaNs at the beginning
        data_filled = data_filtered.ffill().bfill()
        
        # Verify that all requested tickers are present as columns
        final_columns = data_filled.columns.tolist()
        missing_cols = [ticker for ticker in tickers if ticker not in final_columns]
        if missing_cols:
            print(f"Warning: Data for the following tickers could not be retrieved or was all NaN: {', '.join(missing_cols)}")
            # Optionally, drop columns that are all NaN after ffill/bfill
            data_filled = data_filled.dropna(axis=1, how='all')
            if data_filled.empty:
                print("All ticker data was NaN after fill; no valid price data remains.")
                return None


        print("Data fetched and processed successfully.")
        return data_filled
    except Exception as e:
        print(f"An error occurred during historical data fetching: {e}")
        traceback.print_exc()
        return None

def calculate_daily_values(holdings_df, historical_prices, initial_investment):
    """Calculates daily portfolio value and benchmark value."""
    if historical_prices is None or historical_prices.empty:
        empty_series = pd.Series(dtype=float)
        return empty_series, empty_series

    portfolio_value = pd.Series(0.0, index=historical_prices.index)
    
    for date_idx in historical_prices.index:
        current_day_value = 0
        for _, row in holdings_df.iterrows():
            ticker = row['Ticker']
            shares = row['Shares to Buy']
            if ticker in historical_prices.columns and pd.notna(historical_prices.loc[date_idx, ticker]):
                current_day_value += shares * historical_prices.loc[date_idx, ticker]
        portfolio_value[date_idx] = current_day_value

    benchmark_prices = historical_prices[BENCHMARK_TICKER] if BENCHMARK_TICKER in historical_prices.columns else None
    benchmark_value = pd.Series(index=historical_prices.index, dtype=float)

    if benchmark_prices is not None and not benchmark_prices.empty and not benchmark_prices.isna().all():
        # Find the first valid price for the benchmark to scale initial investment
        first_valid_bm_idx = benchmark_prices.first_valid_index()
        if first_valid_bm_idx is not None:
            first_valid_bm_price = benchmark_prices[first_valid_bm_idx]
            if pd.notna(first_valid_bm_price) and first_valid_bm_price > 0 :
                benchmark_shares = initial_investment / first_valid_bm_price
                # Calculate benchmark value only from its first valid price point onwards
                benchmark_value.loc[first_valid_bm_idx:] = benchmark_prices.loc[first_valid_bm_idx:] * benchmark_shares
                benchmark_value.loc[:first_valid_bm_idx] = np.nan # Ensure earlier parts are NaN if no price
                benchmark_value.iloc[0] = initial_investment # Set the first point to initial investment for plotting
            else:
                print("Initial benchmark price is zero, NaN or unavailable. Benchmark performance cannot be calculated accurately.")
                benchmark_value[:] = np.nan
        else: # All benchmark prices are NaN
            print("All benchmark prices are NaN. Benchmark performance cannot be calculated.")
            benchmark_value[:] = np.nan
            
    else:
        print(f"Benchmark ticker {BENCHMARK_TICKER} data not available or all NaN in the selected range. Benchmark performance cannot be calculated.")
        benchmark_value[:] = np.nan

    return portfolio_value, benchmark_value


def calculate_performance_metrics(daily_values_ts, label, risk_free_rate, trading_days_per_year=TRADING_DAYS_PER_YEAR):
    """Calculates key performance metrics for a given time series of values."""
    if daily_values_ts is None or daily_values_ts.empty or daily_values_ts.isna().all():
        print(f"Not enough data to calculate metrics for {label} (series is empty or all NaN).")
        return {
            "Label": label, "Total Return": np.nan, "Annualized Return": np.nan,
            "Annualized Volatility": np.nan, "Sharpe Ratio": np.nan, "Max Drawdown": np.nan,
            "Start Date": "N/A", "End Date": "N/A", "Initial Value": np.nan, "Final Value": np.nan
        }

    valid_values = daily_values_ts.dropna()
    if len(valid_values) < 2:
        start_date_str = valid_values.index[0].strftime('%Y-%m-%d') if len(valid_values) == 1 else "N/A"
        initial_val = valid_values.iloc[0] if len(valid_values) == 1 else np.nan
        print(f"Not enough valid data points (need at least 2) for {label} to calculate returns. Found: {len(valid_values)}")
        return {
            "Label": label, "Total Return": np.nan, "Annualized Return": np.nan,
            "Annualized Volatility": np.nan, "Sharpe Ratio": np.nan, "Max Drawdown": np.nan,
            "Start Date": start_date_str, "End Date": start_date_str,
            "Initial Value": initial_val, "Final Value": initial_val
        }
    
    initial_value = valid_values.iloc[0]
    final_value = valid_values.iloc[-1]
    start_dt = valid_values.index[0]
    end_dt = valid_values.index[-1]

    total_return = (final_value / initial_value) - 1 if initial_value != 0 else np.nan
    
    num_days = (end_dt - start_dt).days
    if num_days == 0: # If only one distinct day's data after dropna (e.g. 2 data points on same day)
        num_years = 1 / trading_days_per_year # Represent as a fraction of a trading year
    else:
        num_years = num_days / 365.25

    annualized_return = np.nan
    if pd.notna(total_return) and num_years > 0:
      annualized_return = (1 + total_return) ** (1 / num_years) - 1
    elif pd.notna(total_return) and num_years == 0 and total_return !=0 : # single period return
      annualized_return = total_return * trading_days_per_year # simple scaling, less accurate

    daily_returns = valid_values.pct_change().dropna() #.pct_change() needs at least 2 points
    
    annualized_volatility = np.nan
    sharpe_ratio = np.nan

    if not daily_returns.empty:
        annualized_volatility = daily_returns.std() * np.sqrt(trading_days_per_year)
        if pd.notna(annualized_volatility) and annualized_volatility != 0 and pd.notna(annualized_return):
            sharpe_ratio = (annualized_return - risk_free_rate) / annualized_volatility
        elif pd.notna(annualized_return) and annualized_return == risk_free_rate and annualized_volatility == 0: # No excess return, no vol
             sharpe_ratio = 0.0 # Or Nan, depending on convention
    
    max_drawdown = np.nan
    if not daily_returns.empty:
        # Max Drawdown calculation needs portfolio values, not just returns
        temp_cumulative_values = (1 + daily_returns).cumprod() * initial_value # Reconstruct value path for drawdown
        peak = temp_cumulative_values.expanding(min_periods=1).max()
        drawdown = (temp_cumulative_values / peak) - 1
        max_drawdown = drawdown.min() if not drawdown.empty else np.nan


    return {
        "Label": label,
        "Start Date": start_dt.strftime('%Y-%m-%d'),
        "End Date": end_dt.strftime('%Y-%m-%d'),
        "Initial Value": initial_value,
        "Final Value": final_value,
        "Total Return": total_return,
        "Annualized Return": annualized_return,
        "Annualized Volatility": annualized_volatility,
        "Sharpe Ratio": sharpe_ratio,
        "Max Drawdown": max_drawdown
    }

def display_results(portfolio_metrics, benchmark_metrics, portfolio_value_ts, benchmark_value_ts):
    """Prints metrics and plots performance."""
    print("\n--- Performance Metrics ---")
    
    metrics_data = []
    if portfolio_metrics: metrics_data.append(portfolio_metrics)
    if benchmark_metrics: metrics_data.append(benchmark_metrics)

    if not metrics_data:
        print("No metrics to display.")
        return

    metrics_df = pd.DataFrame(metrics_data)
    metrics_df.set_index("Label", inplace=True)
    
    # Formatting numerical columns
    for col in ["Initial Value", "Final Value"]:
        metrics_df[col] = metrics_df[col].map('${:,.2f}'.format, na_action='ignore')
    for col in ["Total Return", "Annualized Return", "Annualized Volatility", "Max Drawdown"]:
        metrics_df[col] = (pd.to_numeric(metrics_df[col], errors='coerce') * 100).map('{:.2f}%'.format, na_action='ignore')
    metrics_df["Sharpe Ratio"] = pd.to_numeric(metrics_df["Sharpe Ratio"], errors='coerce').map('{:.2f}'.format, na_action='ignore')
    
    print(metrics_df[['Start Date', 'End Date', 'Initial Value', 'Final Value', 'Total Return', 'Annualized Return', 'Annualized Volatility', 'Sharpe Ratio', 'Max Drawdown']])

    plt.figure(figsize=(14, 7))
    plot_title = 'Portfolio Performance'
    
    can_plot_portfolio = portfolio_value_ts is not None and not portfolio_value_ts.dropna().empty
    can_plot_benchmark = benchmark_value_ts is not None and not benchmark_value_ts.dropna().empty

    portfolio_label = 'Portfolio Value'
    if portfolio_metrics and pd.notna(portfolio_metrics.get('Initial Value')) and can_plot_portfolio:
         portfolio_label += f" (Start ${portfolio_metrics.get('Initial Value'):,.2f})"

    benchmark_label = f'{BENCHMARK_TICKER} Value'
    if benchmark_metrics and pd.notna(benchmark_metrics.get('Initial Value')) and can_plot_benchmark:
        benchmark_label += f" (Scaled Start ${benchmark_metrics.get('Initial Value'):,.2f})"


    if can_plot_portfolio:
        plt.plot(portfolio_value_ts.index, portfolio_value_ts.values, label=portfolio_label, color='blue', linewidth=2)
        plot_title = 'Portfolio Performance'

    if can_plot_benchmark:
        plt.plot(benchmark_value_ts.index, benchmark_value_ts.values, label=benchmark_label, color='grey', linestyle='--')
        if can_plot_portfolio:
             plot_title = f'Portfolio vs. Benchmark ({BENCHMARK_TICKER})'
        else:
             plot_title = f'{BENCHMARK_TICKER} Performance'
    
    if not can_plot_portfolio and not can_plot_benchmark:
        print("\nNeither portfolio nor benchmark data available for plotting.")
        plt.close()
        return

    plt.title(plot_title)
    plt.xlabel('Date')
    plt.ylabel('Value ($)')
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

# --- MAIN EXECUTION ---
def main():
    print("--- Portfolio Performance Checker ---")
    
    portfolio_file_path = input(f"Enter path to portfolio Excel file (default: {DEFAULT_PORTFOLIO_FILE}): ") or DEFAULT_PORTFOLIO_FILE
    
    holdings_df, initial_investment = load_portfolio_from_excel(portfolio_file_path)
    if holdings_df is None or holdings_df.empty:
        print("Exiting due to portfolio loading error.")
        return
    if initial_investment <= 0:
        print("Initial investment from portfolio file is zero or negative. Cannot proceed with performance calculation.")
        return

    start_date, end_date = get_evaluation_period()
    if start_date is None or end_date is None :
        print("Invalid period selected. Exiting.")
        return

    portfolio_tickers = holdings_df['Ticker'].tolist()
    all_tickers_to_fetch = list(set(portfolio_tickers + [BENCHMARK_TICKER]))

    historical_prices = fetch_historical_data(all_tickers_to_fetch, start_date, end_date)
    
    portfolio_value_ts = pd.Series(dtype=float)
    benchmark_value_ts = pd.Series(dtype=float)
    portfolio_metrics = None
    benchmark_metrics = None

    if historical_prices is None or historical_prices.empty:
        print("No historical price data fetched. Cannot calculate performance metrics or plot.")
        portfolio_metrics = calculate_performance_metrics(portfolio_value_ts, "Portfolio", RISK_FREE_RATE) # Will return NaNs
        benchmark_metrics = calculate_performance_metrics(benchmark_value_ts, f"Benchmark ({BENCHMARK_TICKER})", RISK_FREE_RATE) # Will return NaNs
    else:
        # Filter holdings_df to only include tickers for which we actually got price data
        active_tickers_in_prices = [t for t in portfolio_tickers if t in historical_prices.columns]
        if len(active_tickers_in_prices) < len(portfolio_tickers):
            missing_data_for = [t for t in portfolio_tickers if t not in historical_prices.columns]
            print(f"\nWarning: Price data was not available/found for these portfolio tickers (they will be excluded): {', '.join(missing_data_for)}")
        
        active_holdings_df = holdings_df[holdings_df['Ticker'].isin(historical_prices.columns)]
        
        if active_holdings_df.empty and portfolio_tickers:
            print("None of the portfolio tickers have historical price data available for the selected period. Portfolio performance cannot be calculated based on holdings.")
            # Still, create an empty series for consistency if benchmark exists
            portfolio_value_ts = pd.Series(np.nan, index=historical_prices.index if not historical_prices.empty else pd.to_datetime([]))

        elif not portfolio_tickers : # Portfolio was empty to begin with
            print("The loaded portfolio has no holdings.")
            portfolio_value_ts = pd.Series(np.nan, index=historical_prices.index if not historical_prices.empty else pd.to_datetime([]))
        
        # Calculate daily values. `initial_investment` is based on the original Excel file.
        # If some stocks are missing data, their contribution to portfolio_value_ts will be zero.
        # The benchmark is still scaled to the total intended initial_investment.
        portfolio_value_ts, benchmark_value_ts = calculate_daily_values(active_holdings_df, historical_prices, initial_investment)

        portfolio_metrics = calculate_performance_metrics(portfolio_value_ts, "Portfolio", RISK_FREE_RATE)
        benchmark_metrics = calculate_performance_metrics(benchmark_value_ts, f"Benchmark ({BENCHMARK_TICKER})", RISK_FREE_RATE)
    
    display_results(portfolio_metrics, benchmark_metrics, portfolio_value_ts, benchmark_value_ts)

if __name__ == '__main__':
    main()
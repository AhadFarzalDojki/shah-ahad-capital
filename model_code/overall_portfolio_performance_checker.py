import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

def analyze_portfolio(start_date_str, end_date_str, portfolio_allocations, annual_risk_free_rate):
    TRADING_DAYS_PER_YEAR = 252

    # Initialize return values
    annualized_portfolio_std_dev = np.nan
    annualized_sp500_std_dev = np.nan
    portfolio_sharpe_ratio_geometric = np.nan
    sp500_sharpe_ratio_geometric = np.nan
    holding_details_df = pd.DataFrame()
    portfolio_total_value_ts = None
    sp500_equivalent_value_ts = None
    annualized_portfolio_geometric_return = np.nan
    annualized_sp500_geometric_return = np.nan

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        yf_end_date = end_date + timedelta(days=1)

        # Calculate approximated number of trading days in the period
        calendar_days_in_period = (end_date - start_date).days + 1
        if calendar_days_in_period <= 0: # Should not happen with date validation in main
            print("Warning: Calendar days in period is zero or negative. Setting approximated trading days to 1.")
            approximated_trading_days_in_period = 1
        else:
            approximated_trading_days_in_period = max(1, round(calendar_days_in_period * (4.83/7)))
        print(f"Calendar days in period: {calendar_days_in_period}, Approximated trading days for geometric annualization: {approximated_trading_days_in_period}")


        all_tickers = list(portfolio_allocations.keys())
        benchmark_ticker = 'SPY'

        print(f"Fetching data for tickers: {', '.join(all_tickers + [benchmark_ticker])}")
        print(f"From {start_date_str} to {end_date_str}")

        if start_date.date() > datetime.now().date():
            print(f"\nWARNING: The start date {start_date_str} is in the future.")

        data = yf.download(all_tickers + [benchmark_ticker], start=start_date, end=yf_end_date, progress=False)['Close']

        if data.empty:
            print("No data fetched.")
            return np.nan, np.nan, np.nan, np.nan, pd.DataFrame(), None, None, np.nan, np.nan

        data = data.dropna(how='all')
        full_date_range = pd.date_range(start=start_date, end=end_date, name='Date')
        data = data.reindex(full_date_range.union(data.index)).sort_index()
        data = data.loc[start_date:end_date]
        data = data.ffill().bfill()

        if data.empty or data.isnull().all().all():
            print("No valid data remaining after processing.")
            return np.nan, np.nan, np.nan, np.nan, pd.DataFrame(), None, None, np.nan, np.nan

        if data.isnull().any().any():
            print("Warning: Missing data found for some tickers even after fill.")
            print(data.isnull().sum()[data.isnull().sum() > 0])

        initial_prices = data.iloc[0]
        final_prices = data.iloc[-1]

        # Calculate holding details
        holding_details_list = []
        for ticker, initial_investment in portfolio_allocations.items():
            start_price = initial_prices.get(ticker, np.nan)
            end_price = final_prices.get(ticker, np.nan)
            num_shares = np.nan
            holding_percent_return = np.nan
            current_value_of_holding = np.nan
            if pd.notna(start_price) and start_price > 0:
                num_shares = initial_investment / start_price
                if pd.notna(end_price):
                    current_value_of_holding = num_shares * end_price
                    holding_percent_return = ((end_price / start_price) - 1) * 100
            holding_details_list.append({
                'Ticker': ticker, 'Initial Investment': initial_investment, 'Shares Bought': num_shares,
                'Price at Start': start_price, 'Price at End': end_price, 'Value at End': current_value_of_holding,
                'Percent Return (%)': holding_percent_return
            })
        holding_details_df = pd.DataFrame(holding_details_list)

        # Calculate portfolio value over time
        portfolio_value_over_time = pd.DataFrame(index=data.index)
        for ticker, initial_investment_amount in portfolio_allocations.items():
            if ticker in data.columns and ticker in initial_prices and not pd.isna(initial_prices[ticker]) and initial_prices[ticker] != 0:
                normalized_prices = data[ticker] / initial_prices[ticker]
                portfolio_value_over_time[ticker] = normalized_prices * initial_investment_amount
            else:
                portfolio_value_over_time[ticker] = pd.Series(initial_investment_amount, index=data.index)
        portfolio_value_over_time['Total Portfolio'] = portfolio_value_over_time.sum(axis=1)
        portfolio_total_value_ts = portfolio_value_over_time['Total Portfolio']

        if portfolio_total_value_ts.empty or portfolio_total_value_ts.count() < 2:
            print("Portfolio total value time series has less than two data points.")
            return np.nan, np.nan, np.nan, np.nan, holding_details_df, None, None, np.nan, np.nan

        portfolio_daily_returns = portfolio_total_value_ts.pct_change().dropna()

        # Portfolio Standard Deviation & Geometric Sharpe Ratio
        if not portfolio_daily_returns.empty and len(portfolio_daily_returns) >= 1: # Std dev needs at least 1 return, geom needs positive base
            portfolio_std_dev_daily = portfolio_daily_returns.std()
            if pd.notna(portfolio_std_dev_daily) and portfolio_std_dev_daily > 0:
                annualized_portfolio_std_dev = portfolio_std_dev_daily * np.sqrt(TRADING_DAYS_PER_YEAR)
            elif pd.notna(portfolio_std_dev_daily) and portfolio_std_dev_daily == 0:
                annualized_portfolio_std_dev = 0.0
                print("Portfolio daily returns standard deviation is zero.")
            else:
                print("Portfolio standard deviation could not be calculated (NaN).")
                annualized_portfolio_std_dev = np.nan # Ensure it's NaN if calc failed

            # Calculate Annualized Geometric Return for Portfolio
            initial_portfolio_value = portfolio_total_value_ts.iloc[0]
            final_portfolio_value = portfolio_total_value_ts.iloc[-1]
            # num_periods_portfolio is now approximated_trading_days_in_period for geometric annualization

            if initial_portfolio_value != 0 and approximated_trading_days_in_period > 0:
                total_portfolio_return_period = (final_portfolio_value / initial_portfolio_value) - 1
                if (1 + total_portfolio_return_period) >= 0: # Allow 100% loss (base = 0)
                     annualized_portfolio_geometric_return = (1 + total_portfolio_return_period)**(TRADING_DAYS_PER_YEAR / approximated_trading_days_in_period) - 1
                     if pd.notna(annualized_portfolio_std_dev) and annualized_portfolio_std_dev > 0:
                         portfolio_sharpe_ratio_geometric = (annualized_portfolio_geometric_return - annual_risk_free_rate) / annualized_portfolio_std_dev
                     elif annualized_portfolio_std_dev == 0 and annualized_portfolio_geometric_return != annual_risk_free_rate:
                         portfolio_sharpe_ratio_geometric = np.inf if annualized_portfolio_geometric_return > annual_risk_free_rate else -np.inf
                     else: # std_dev is 0 and return equals risk-free, or std_dev is NaN
                         portfolio_sharpe_ratio_geometric = np.nan
                else: # Handle >100% loss (though unlikely with portfolio values)
                    annualized_portfolio_geometric_return = -1.0 # Total loss or more
                    portfolio_sharpe_ratio_geometric = np.nan # Sharpe undefined
                    print("Portfolio experienced a 100% or greater loss; geometric return is -100%.")
            else:
                 print("Cannot calculate annualized geometric portfolio return due to zero initial value or zero approximated trading days.")


        else: # Not enough portfolio daily returns for std dev
            print("Not enough portfolio daily returns to calculate standard deviation. Geometric metrics that depend on it might also be affected.")
            # Still try to calculate geometric return if possible, even if std dev is NaN
            initial_portfolio_value = portfolio_total_value_ts.iloc[0]
            final_portfolio_value = portfolio_total_value_ts.iloc[-1]
            if initial_portfolio_value != 0 and approximated_trading_days_in_period > 0 and portfolio_total_value_ts.count() >= 1: # Need at least one value for total return
                total_portfolio_return_period = (final_portfolio_value / initial_portfolio_value) - 1
                if (1 + total_portfolio_return_period) >= 0:
                    annualized_portfolio_geometric_return = (1 + total_portfolio_return_period)**(TRADING_DAYS_PER_YEAR / approximated_trading_days_in_period) - 1
                else:
                    annualized_portfolio_geometric_return = -1.0
            portfolio_sharpe_ratio_geometric = np.nan # Sharpe requires std dev


        # S&P 500 (SPY) Analysis
        sp500_daily_returns = pd.Series(dtype=float)
        initial_total_investment = sum(portfolio_allocations.values())

        if benchmark_ticker in data.columns and not data[benchmark_ticker].isnull().all() and data[benchmark_ticker].count() >=2 :
            if benchmark_ticker in initial_prices and not pd.isna(initial_prices[benchmark_ticker]) and initial_prices[benchmark_ticker] != 0:
                sp500_equivalent_value_ts = (data[benchmark_ticker] / initial_prices[benchmark_ticker]) * initial_total_investment
            else:
                sp500_equivalent_value_ts = None
                print(f"Warning: Could not calculate S&P 500 equivalent value due to missing initial price for {benchmark_ticker}.")

            if sp500_equivalent_value_ts is not None and not sp500_equivalent_value_ts.empty and sp500_equivalent_value_ts.count() >=2:
                sp500_daily_returns = data[benchmark_ticker].pct_change().dropna()

                if not sp500_daily_returns.empty and len(sp500_daily_returns) >= 1:
                    sp500_std_dev_daily = sp500_daily_returns.std()
                    if pd.notna(sp500_std_dev_daily) and sp500_std_dev_daily > 0:
                        annualized_sp500_std_dev = sp500_std_dev_daily * np.sqrt(TRADING_DAYS_PER_YEAR)
                    elif pd.notna(sp500_std_dev_daily) and sp500_std_dev_daily == 0:
                        annualized_sp500_std_dev = 0.0
                        print(f"S&P 500 ({benchmark_ticker}) daily returns standard deviation is zero.")
                    else:
                        print(f"S&P 500 ({benchmark_ticker}) standard deviation could not be calculated (NaN).")
                        annualized_sp500_std_dev = np.nan


                    # Calculate Annualized Geometric Return for SPY
                    initial_sp500_val_calc = sp500_equivalent_value_ts.iloc[0]
                    final_sp500_val_calc = sp500_equivalent_value_ts.iloc[-1]
                    # num_periods_spy is now approximated_trading_days_in_period

                    if initial_sp500_val_calc != 0 and approximated_trading_days_in_period > 0:
                        total_sp500_return_period = (final_sp500_val_calc / initial_sp500_val_calc) - 1
                        if (1 + total_sp500_return_period) >= 0: # Allow 100% loss
                            annualized_sp500_geometric_return = (1 + total_sp500_return_period)**(TRADING_DAYS_PER_YEAR / approximated_trading_days_in_period) - 1
                            if pd.notna(annualized_sp500_std_dev) and annualized_sp500_std_dev > 0:
                                sp500_sharpe_ratio_geometric = (annualized_sp500_geometric_return - annual_risk_free_rate) / annualized_sp500_std_dev
                            elif annualized_sp500_std_dev == 0 and annualized_sp500_geometric_return != annual_risk_free_rate:
                                 sp500_sharpe_ratio_geometric = np.inf if annualized_sp500_geometric_return > annual_risk_free_rate else -np.inf
                            else:
                                sp500_sharpe_ratio_geometric = np.nan
                        else:
                            annualized_sp500_geometric_return = -1.0
                            sp500_sharpe_ratio_geometric = np.nan
                            print("S&P 500 experienced a 100% or greater loss; geometric return is -100%.")
                    else:
                        print(f"Cannot calculate annualized geometric S&P 500 return due to zero initial value or zero approximated trading days.")

                else: # Not enough SPY daily returns for std dev
                    print(f"Not enough S&P 500 ({benchmark_ticker}) daily returns for standard deviation.")
                    initial_sp500_val_calc = sp500_equivalent_value_ts.iloc[0]
                    final_sp500_val_calc = sp500_equivalent_value_ts.iloc[-1]
                    if initial_sp500_val_calc != 0 and approximated_trading_days_in_period > 0 and sp500_equivalent_value_ts.count() >= 1:
                        total_sp500_return_period = (final_sp500_val_calc / initial_sp500_val_calc) - 1
                        if (1 + total_sp500_return_period) >= 0:
                            annualized_sp500_geometric_return = (1 + total_sp500_return_period)**(TRADING_DAYS_PER_YEAR / approximated_trading_days_in_period) - 1
                        else:
                            annualized_sp500_geometric_return = -1.0
                    sp500_sharpe_ratio_geometric = np.nan
            else:
                 print(f"S&P 500 ({benchmark_ticker}) equivalent value time series has less than two data points.")
        else:
            print(f"Warning: S&P 500 ({benchmark_ticker}) data not available or insufficient for the period.")

        return (annualized_portfolio_std_dev,
                annualized_sp500_std_dev,
                portfolio_sharpe_ratio_geometric,
                sp500_sharpe_ratio_geometric,
                holding_details_df,
                portfolio_total_value_ts,
                sp500_equivalent_value_ts,
                annualized_portfolio_geometric_return,
                annualized_sp500_geometric_return)

    except Exception as e:
        print(f"An error occurred in analyze_portfolio: {e}")
        import traceback
        traceback.print_exc()
        return np.nan, np.nan, np.nan, np.nan, pd.DataFrame(), None, None, np.nan, np.nan


def get_date_input(prompt_message):
    """Prompts user for a date and validates its format (YYYY-MM-DD)."""
    while True:
        date_str = input(prompt_message)
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            return date_str
        except ValueError:
            print("Invalid date format. Please use YYYY-MM-DD.")

if __name__ == '__main__':
    ANNUAL_RISK_FREE_RATE = 0.04301

    print("Please enter the dates for the analysis.")
    start_date_string = get_date_input("Enter start date (YYYY-MM-DD): ")
    end_date_string = get_date_input("Enter end date (YYYY-MM-DD): ")

    # Validate end_date is not before start_date
    s_date_obj = datetime.strptime(start_date_string, '%Y-%m-%d')
    e_date_obj = datetime.strptime(end_date_string, '%Y-%m-%d')

    while e_date_obj < s_date_obj:
        print("End date cannot be before start date. Please enter dates again.")
        start_date_string = get_date_input("Enter start date (YYYY-MM-DD): ")
        end_date_string = get_date_input("Enter end date (YYYY-MM-DD): ")
        s_date_obj = datetime.strptime(start_date_string, '%Y-%m-%d')
        e_date_obj = datetime.strptime(end_date_string, '%Y-%m-%d')


    if start_date_string == end_date_string:
        print("\nWarning: Start date and end date are the same. Calculations will be based on a single day's data (or approximation for N=1).")
        print("Returns will be 0% if using the same day's open/close, or if data hasn't changed.")
        print("Standard deviation will likely be zero or NaN. Sharpe ratio will be NaN or Inf.")


    algo_stocks_v1 = ['ULTA', 'CHTR', 'UBER', 'CF', 'TRMB', 'UAL', 'NRG', 'RCL', 'EBAY', 'WDC', 'SYF', 'NEM', 'NTRS', 'HIG', 'MPWR', 'MMM', 'FOXA', 'FOX', 'WRB', 'GL', 'CCL', 'VST', 'DRI', 'RL','ALL']
    algo_stocks_v2 = ['GOOGL','GILD','META','LRCX','PDD','IDXX','QCOM','CSX','NVDA','BKR','ROST','CMCSA','APP','KLAC','TMUS']
    algo_stocks_v3 = ['TTI', 'SBH', 'SIGA', 'UPWK', 'IBEX', 'BBW', 'VSCO', 'GCT', 'HRTG', 'STNG', 'APP', 'MU', 'LRCX', 'KLAC', 'ASML', 'AMAT', 'PDD', 'META', 'QCOM', 'BKR', 'WDC', 'ULTA', 'CAT', 'CMI', 'LDOS', 'MPWR', 'EBAY', 'NEM', 'GOOGL', 'NVDA']
    if len(algo_stocks_v3) != 15 or 'TICKER2' in algo_stocks_v3 : # Basic check
         print("WARNING: Please ensure 'first_15_tickers_placeholder' is correctly populated with 15 unique stock tickers if that's the intention.")

    allocations = {
        # Portfolio V3:
        **{ticker: 26666.67 for ticker in algo_stocks_v3},
        'GLD': 100000, 'BNDX': 100000,
        # Portfolio V2:
        # 'SPY': 450000,
        # **{ticker: 26666.67 for ticker in algo_stocks_v2},
        # 'MSFT': 25000, 'AMZN': 25000, 'AMD': 25000, 'JNJ': 25000,
        # 'ETH-USD': 50000, 
        # 'VST': 12500, 'EXPE': 12500, 'RKLB': 12500, 'RGTI': 12500
        # Portfolio V1: 
        #'QQQ': 100000, 'AIQ': 100000, 'BRK-B': 100000,
        #**{ticker: 10000 for ticker in algo_stocks_v1},
        #'GLD': 200000, 'NVDA': 25000, 'TSM': 25000, 'ASML': 25000, 'GOOGL': 25000,
        #'BTC-USD': 75000, 'GRRR': 25000, 'INOD': 25000, 'RKLB': 12500, 'RGTI': 12500,
        # Portfolio V0: 
        # 'QQQ': 500, 'AIQ': 100, 'BRK-B': 200, 'NVDA': 250, 'GRRR': 250, 'GOOGL': 100, 'TSM': 50, 'ASML': 50, 'INOD': 100, 'RGTI': 25,
        # 'BBAI': 50, 'VST': 150, 'SOUN': 50, 'LUNR': 25, 'AISP': 50, 'RKLB': 50,
    }
    # Ensure all tickers in allocations are strings
    allocations = {str(k): v for k, v in allocations.items()}


    (portfolio_std, sp500_std,
     portfolio_sharpe, sp500_sharpe,
     holdings_df,
     portfolio_value_ts, sp500_performance_ts,
     portfolio_annual_geom_return, sp500_annual_geom_return) = \
        analyze_portfolio(start_date_string, end_date_string, allocations, ANNUAL_RISK_FREE_RATE)

    print("\n--- Portfolio Holding Details ---")
    if not holdings_df.empty:
        pd.set_option('display.float_format', lambda x: f'{x:,.2f}' if pd.notna(x) else 'N/A')
        print(holdings_df.to_string())
        pd.reset_option('display.float_format')
    else:
        print("Holding details could not be calculated.")

    print("\n--- Overall Portfolio Performance ---")
    if portfolio_value_ts is not None and not portfolio_value_ts.empty:
        print(f"Period: {start_date_string} to {end_date_string}")
        initial_portfolio_value = portfolio_value_ts.iloc[0]
        final_portfolio_value = portfolio_value_ts.iloc[-1]

        if initial_portfolio_value != 0:
            portfolio_return_total_period = (final_portfolio_value / initial_portfolio_value - 1) * 100
            print(f"Portfolio Total Return (Period): {portfolio_return_total_period:.2f}%")
        else:
            print("Portfolio Total Return (Period): Cannot be calculated (initial value is zero).")

        if not np.isnan(portfolio_annual_geom_return):
            print(f"Portfolio Annualized Geometric Return (N approx. 4.83/7 calendar): {portfolio_annual_geom_return*100:.2f}%")
        else:
            print("Portfolio Annualized Geometric Return (N approx. 4.83/7 calendar): Could not be calculated.")

        print(f"Initial Portfolio Value: ${initial_portfolio_value:,.2f}")
        print(f"Final Portfolio Value: ${final_portfolio_value:,.2f}")

        if not np.isnan(portfolio_std):
            print(f"Portfolio Annualized Standard Deviation: {portfolio_std:.4f} ({portfolio_std*100:.2f}%)")
        else:
            print("Portfolio Annualized Standard Deviation: Could not be calculated.")

        if not np.isnan(portfolio_sharpe):
            print(f"Portfolio Annualized Sharpe Ratio (Geometric, Rf={ANNUAL_RISK_FREE_RATE*100:.3f}%): {portfolio_sharpe:.3f}")
        else:
            print(f"Portfolio Annualized Sharpe Ratio (Geometric, Rf={ANNUAL_RISK_FREE_RATE*100:.3f}%): Could not be calculated.")
    else:
        print("Overall portfolio performance data is unavailable or empty.")

    print("\n--- S&P 500 (SPY) Benchmark Performance ---")
    if sp500_performance_ts is not None and not sp500_performance_ts.empty:
        initial_sp500_value = sp500_performance_ts.iloc[0]
        final_sp500_value = sp500_performance_ts.iloc[-1]
        if initial_sp500_value != 0:
            sp500_return_total_period = (final_sp500_value / initial_sp500_value - 1) * 100
            print(f"S&P 500 (SPY) Total Return for period: {sp500_return_total_period:.2f}%")
        else:
            print("S&P 500 (SPY) Total Return: Cannot be calculated (initial SPY equivalent value is zero).")

        if not np.isnan(sp500_annual_geom_return):
            print(f"S&P 500 (SPY) Annualized Geometric Return (N approx. 4.83/7 calendar): {sp500_annual_geom_return*100:.2f}%")
        else:
            print("S&P 500 (SPY) Annualized Geometric Return (N approx. 4.83/7 calendar): Could not be calculated.")

        if not np.isnan(sp500_std):
            print(f"S&P 500 (SPY) Annualized Standard Deviation: {sp500_std:.4f} ({sp500_std*100:.2f}%)")
        else:
            print("S&P 500 (SPY) Annualized Standard Deviation: Could not be calculated.")

        if not np.isnan(sp500_sharpe):
            print(f"S&P 500 (SPY) Annualized Sharpe Ratio (Geometric, Rf={ANNUAL_RISK_FREE_RATE*100:.3f}%): {sp500_sharpe:.3f}")
        else:
            print(f"S&P 500 (SPY) Annualized Sharpe Ratio (Geometric, Rf={ANNUAL_RISK_FREE_RATE*100:.3f}%): Could not be calculated.")
    else:
        print("S&P 500 (SPY) benchmark performance data is unavailable or empty.")

    # --- Plotting --- (remains the same)
    if portfolio_value_ts is not None and not portfolio_value_ts.empty:
        plt.figure(figsize=(14, 8))
        plt.plot(portfolio_value_ts.index, portfolio_value_ts, label='Portfolio Value', linewidth=2, color='blue')
        if sp500_performance_ts is not None and not sp500_performance_ts.empty:
            plt.plot(sp500_performance_ts.index, sp500_performance_ts, label='S&P 500 (SPY) Equivalent Growth', linestyle='--', linewidth=2, color='orange')
        plt.title(f'Portfolio Performance vs. S&P 500 (SPY)\n{start_date_string} to {end_date_string}', fontsize=16)
        plt.xlabel('Date', fontsize=12)
        plt.ylabel('Value (USD)', fontsize=12)
        formatter = mticker.FormatStrFormatter('$%.0f')
        plt.gca().yaxis.set_major_formatter(formatter)
        plt.legend(fontsize=11)
        plt.grid(True, linestyle=':', alpha=0.6)
        plt.xticks(rotation=30, ha='right')
        plt.tight_layout()
        plt.show()
    else:
        print("\nCould not generate performance plot as portfolio value data is unavailable or empty.")
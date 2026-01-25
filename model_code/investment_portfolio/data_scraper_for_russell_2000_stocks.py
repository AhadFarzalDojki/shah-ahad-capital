import requests
from bs4 import BeautifulSoup
import pandas as pd
import yfinance as yf
import time
import random
import numpy as np
from datetime import datetime, timedelta

# --- CONFIGURATION ---
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
SCRAPE_REQUEST_DELAY_SECONDS = 2  # Time to wait between web scraping requests
YFINANCE_REQUEST_DELAY_SECONDS = 0.5 # yfinance might handle its own rate limiting, but a small delay is still good practice.
OUTPUT_FILENAME = 'russell_2000_financial_data_with_momentum.csv'
TICKERS_FILENAME = 'russell_2000_tickers.csv' # The local CSV file with Russell 2000 tickers

# --- HELPER FUNCTIONS ---

def get_russell_2000_tickers_from_csv():
    """
    Reads a list of Russell 2000 tickers from a local CSV file.
    The CSV file should be named 'russell_2000_tickers.csv' and have a 'Ticker' column.
    Returns a list of tickers.
    """
    print(f"Reading Russell 2000 ticker list from '{TICKERS_FILENAME}'...")
    try:
        df = pd.read_csv(TICKERS_FILENAME)
        if 'Ticker' not in df.columns:
            print(f"Error: The file '{TICKERS_FILENAME}' must have a column named 'Ticker'.")
            return []
        tickers = df['Ticker'].dropna().tolist()
        # Clean up tickers: remove extra whitespace and handle potential variations
        tickers = [str(ticker).strip().replace('.', '-') for ticker in tickers]
        print(f"Successfully read {len(tickers)} Russell 2000 tickers.")
        return tickers
    except FileNotFoundError:
        print(f"Error: Ticker file '{TICKERS_FILENAME}' not found.")
        print("Please create this file in the same directory with a 'Ticker' column containing the stock symbols.")
        return []
    except Exception as e:
        print(f"An error occurred while reading the ticker file: {e}")
        return []


def scrape_finviz_ratios(ticker):
    """
    Scrapes P/E, P/B, P/S, ROE, EV/EBITDA for a single stock ticker from Finviz.com.
    Returns a dictionary with the scraped data.
    """
    print(f"Scraping Finviz for ratios of {ticker}...")
    url = f"https://finviz.com/quote.ashx?t={ticker}"
    headers = {'User-Agent': USER_AGENT}
    ratio_data = {'Ticker': ticker}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')

        table = soup.find('table', class_='snapshot-table2')
        if not table:
            print(f"Could not find snapshot-table2 for {ticker} on Finviz. Ratios will be NaN.")
            return {
                'Ticker': ticker, 'P/E Ratio': np.nan, 'P/B Ratio': np.nan,
                'P/S Ratio': np.nan, 'ROE': np.nan, 'EV/EBITDA': np.nan
            }

        all_tds = table.find_all('td')
        metric_map = {}
        for i in range(0, len(all_tds), 2):
            if i + 1 < len(all_tds):
                metric_name = all_tds[i].text.strip()
                metric_value = all_tds[i+1].text.strip()
                metric_map[metric_name] = metric_value

        def get_metric_value(name):
            val = metric_map.get(name)
            if val and val != '-':
                try:
                    return float(val)
                except ValueError:
                    return np.nan # Cannot convert
            return np.nan # Missing or '-'

        ratio_data['P/E Ratio'] = get_metric_value('P/E')
        ratio_data['P/B Ratio'] = get_metric_value('P/B')
        ratio_data['P/S Ratio'] = get_metric_value('P/S')
        ratio_data['EV/EBITDA'] = get_metric_value('EV/EBITDA')

        roe_str = metric_map.get('ROE')
        if roe_str and roe_str != '-':
            try:
                ratio_data['ROE'] = float(roe_str.rstrip('%')) / 100.0
            except ValueError:
                ratio_data['ROE'] = np.nan
        else:
            ratio_data['ROE'] = np.nan

        return ratio_data

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404: print(f"Stock {ticker} not found on Finviz (404). Ratios NaN.")
        elif e.response.status_code == 403: print(f"Access denied for {ticker} on Finviz (403). Ratios NaN.")
        else: print(f"HTTP error for {ticker} on Finviz: {e}. Ratios NaN.")
        return {
            'Ticker': ticker, 'P/E Ratio': np.nan, 'P/B Ratio': np.nan,
            'P/S Ratio': np.nan, 'ROE': np.nan, 'EV/EBITDA': np.nan
        }
    except Exception as e:
        print(f"Error parsing ratio data for {ticker} from Finviz: {e}. Ratios NaN.")
        return {
            'Ticker': ticker, 'P/E Ratio': np.nan, 'P/B Ratio': np.nan,
            'P/S Ratio': np.nan, 'ROE': np.nan, 'EV/EBITDA': np.nan
        }

def get_yfinance_data(ticker_symbol):
    """
    Fetches current price and calculates momentum returns using yfinance.
    Prioritizes 'Close' column for adjusted prices from Ticker.history().
    """
    print(f"Fetching yfinance data for {ticker_symbol}...")
    stock_yf_data = {'Ticker': ticker_symbol} # Add ticker to the dict early

    try:
        stock = yf.Ticker(ticker_symbol)
        info = stock.info

        # Current Price
        current_price = info.get('currentPrice', info.get('regularMarketPreviousClose', info.get('previousClose'))) # Added regularMarketPreviousClose as another common key
        if current_price is None:
             # Try to get last close from a minimal history call if info fails
             hist_1d = stock.history(period="1d")
             if not hist_1d.empty and 'Close' in hist_1d.columns:
                 current_price = hist_1d['Close'].iloc[-1]
             else:
                 print(f"Warning: Could not determine current price for {ticker_symbol} from info or 1d history.")
                 current_price = np.nan
        stock_yf_data['Price'] = current_price

        # Momentum Metrics
        # Ticker.history() default auto_adjust=True means 'Close' is adjusted.
        hist_df = stock.history(period="1y", interval="1d")

        price_series_for_momentum = None # Initialize

        if not hist_df.empty:
            if 'Close' in hist_df.columns:
                price_series_for_momentum = hist_df['Close']
                # print(f"Info for {ticker_symbol}: Using 'Close' column for momentum calculations (assumed adjusted).")
            elif 'Adj Close' in hist_df.columns: # Fallback, in case 'Close' is missing but 'Adj Close' is present
                price_series_for_momentum = hist_df['Adj Close']
                print(f"Info for {ticker_symbol}: 'Close' column not found. Using 'Adj Close' column for momentum.")
            else:
                print(f"Warning for {ticker_symbol}: Neither 'Close' nor 'Adj Close' found in historical data. Momentum will be NaN.")
        else:
            print(f"Warning for {ticker_symbol}: No historical data returned by yfinance. Momentum will be NaN.")

        ret_1m, ret_3m, ret_6m, ret_12m = np.nan, np.nan, np.nan, np.nan # Default to NaN

        if price_series_for_momentum is not None and not price_series_for_momentum.empty:
            if len(price_series_for_momentum) >= 21: # Sufficient data for most metrics
                current_price_for_momentum = price_series_for_momentum.iloc[-1]
                periods = {'1M': 21, '3M': 63, '6M': 126, '12M': 252}

                def get_return(series, current_val, days_ago_period):
                    if len(series) > days_ago_period:
                        price_then = series.iloc[-(days_ago_period + 1)]
                        if pd.notna(price_then) and price_then != 0:
                            return (current_val - price_then) / price_then
                    # Special handling for 12M if data is almost a year long but not exactly 252+ days
                    elif days_ago_period == periods['12M'] and len(series) >= (periods['12M'] * 0.9):
                        price_then = series.iloc[0] # Use the earliest available point
                        if pd.notna(price_then) and price_then != 0:
                             return (current_val - price_then) / price_then
                    return np.nan

                ret_1m = get_return(price_series_for_momentum, current_price_for_momentum, periods['1M'])
                ret_3m = get_return(price_series_for_momentum, current_price_for_momentum, periods['3M'])
                ret_6m = get_return(price_series_for_momentum, current_price_for_momentum, periods['6M'])
                ret_12m = get_return(price_series_for_momentum, current_price_for_momentum, periods['12M'])

            else: # Data exists but is shorter than 21 trading days
                print(f"Warning: Insufficient historical data length ({len(price_series_for_momentum)} days) for {ticker_symbol} for full momentum. Some returns may be NaN.")
                # Still attempt to calculate overall return if at least two points exist (as '12M return')
                if len(price_series_for_momentum) > 1:
                    current_price_for_momentum = price_series_for_momentum.iloc[-1]
                    price_then = price_series_for_momentum.iloc[0]
                    if pd.notna(price_then) and price_then != 0:
                        ret_12m = (current_price_for_momentum - price_then) / price_then
        # If price_series_for_momentum was None or empty, all rets remain NaN, warnings already printed.

        stock_yf_data['1M Return'] = ret_1m
        stock_yf_data['3M Return'] = ret_3m
        stock_yf_data['6M Return'] = ret_6m
        stock_yf_data['12M Return'] = ret_12m

        return stock_yf_data

    except Exception as e:
        print(f"General error processing {ticker_symbol} with yfinance: {e}")
        # Ensure all expected keys are present even on total failure
        return {
            'Ticker': ticker_symbol,
            'Price': np.nan,
            '1M Return': np.nan, '3M Return': np.nan,
            '6M Return': np.nan, '12M Return': np.nan
        }

# --- MAIN LOGIC ---
def main():
    print("Starting Russell 2000 data collection process (Fundamentals via scraping, Price/Momentum via yfinance)...")

    tickers = get_russell_2000_tickers_from_csv()
    if not tickers:
        print("No tickers loaded. Exiting.")
        return

    all_stock_data_combined = []
    processed_count = 0

    # You can uncomment the line below to test with a smaller list of tickers first
    # tickers = tickers[:25] # Test with first 25 tickers

    for ticker in tickers:
        print(f"\nProcessing Ticker: {ticker} ({processed_count + 1}/{len(tickers)})")

        # 1. Scrape fundamental ratios from Finviz
        fundamental_ratios = scrape_finviz_ratios(ticker)
        time.sleep(SCRAPE_REQUEST_DELAY_SECONDS + random.uniform(0, 0.5)) # Polite delay

        # 2. Fetch price and momentum data from yfinance
        price_momentum_data = get_yfinance_data(ticker)
        # yfinance can sometimes be slow or have internal rate limiting, a small breather
        time.sleep(YFINANCE_REQUEST_DELAY_SECONDS + random.uniform(0,0.2))


        # 3. Combine data
        combined_data = {'Ticker': ticker}
        combined_data.update(fundamental_ratios) # Adds P/E, P/B, P/S, ROE, EV/EBITDA
        combined_data.update(price_momentum_data) # Adds Price, and returns. yfinance Price will overwrite Finviz if present.

        all_stock_data_combined.append(combined_data)
        processed_count += 1

    if not all_stock_data_combined:
        print("No data was collected. Exiting.")
        return

    # Create DataFrame
    final_df = pd.DataFrame(all_stock_data_combined)

    # Define column order for the CSV
    columns_order = [
        'Ticker', 'Price', 'P/E Ratio', 'P/S Ratio', 'P/B Ratio',
        'ROE', 'EV/EBITDA',
        '1M Return', '3M Return', '6M Return', '12M Return'
    ]
    # Ensure all desired columns exist, add them with np.nan if they don't (e.g. if a key was missed in dict creation)
    for col in columns_order:
        if col not in final_df.columns:
            final_df[col] = np.nan

    final_df = final_df[columns_order] # Reorder/select columns

    try:
        final_df.to_csv(OUTPUT_FILENAME, index=False, float_format='%.4f') # Save with 4 decimal places for floats
        print(f"\nCombined financial data saved to '{OUTPUT_FILENAME}'")
        print("\nSample of collected data:")
        print(final_df.head())
        print(f"\nTotal stocks processed: {len(final_df)}")
        print(f"Stocks with missing Price: {final_df['Price'].isnull().sum()}")
        print(f"Stocks with missing P/E Ratio: {final_df['P/E Ratio'].isnull().sum()}")
        print(f"Stocks with missing 12M Return: {final_df['12M Return'].isnull().sum()}")
    except Exception as e:
        print(f"Error saving data to CSV: {e}")

    print("\n--- IMPORTANT NOTES ---")
    print("1. Web scraping (for P/E, P/B, P/S, ROE, EV/EBITDA from Finviz) is fragile and may break if Finviz.com changes.")
    print("2. Be respectful of website terms of service. Delays are included.")
    print("3. Data accuracy depends on the sources (Finviz, Yahoo Finance). Inconsistencies or missing data (NaN) can occur.")
    print("4. Not all ratios (especially EV/EBITDA) might be available for all stocks on Finviz.")
    print("5. yfinance data is generally reliable but can also have occasional gaps or issues.")

if __name__ == '__main__':
    main()
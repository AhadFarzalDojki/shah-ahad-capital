 # fetch_market_data.py

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging
import os # Make sure os is imported

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_valid_fetch_date_range() -> tuple[datetime, datetime] or tuple[None, None]:
    """Prompts the user to enter a start and end date for data fetching."""
    start_date, end_date = None, None
    while True:
        start_date_str = input("Enter the START date for data fetching (YYYY-MM-DD): ")
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            break
        except ValueError:
            print("Invalid start date format. Please use YYYY-MM-DD.")

    while True:
        end_date_str = input("Enter the END date for data fetching (YYYY-MM-DD): ")
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            if end_date < start_date:
                print("End date cannot be before the start date.")
                continue
            if end_date > datetime.now() + timedelta(days=2):
                print("Warning: Fetching data for future dates. Data may not be complete.")
            break
        except ValueError:
            print("Invalid end date format. Please use YYYY-MM-DD.")
    return start_date, end_date

def fetch_and_prepare_data(start_date: datetime, end_date: datetime,
                           index_ticker: str = 'SPY', vix_ticker: str = '^VIX',
                           output_directory: str = r'C:\Users\shahr\Downloads\Shahad Capital\Market Regime Analysis',
                           csv_filename: str = 'SPY-VIX_data.csv'
                           ) -> bool:
    """
    Fetches market data, calculates SMAs, merges, and saves to CSV.
    """
    try:
        full_output_path = os.path.join(output_directory, csv_filename)

        if not os.path.exists(output_directory):
            try:
                os.makedirs(output_directory)
                logging.info(f"Created directory: {output_directory}")
            except OSError as e:
                logging.error(f"Could not create directory {output_directory}: {e}")
                return False

        fetch_start_date_sma = start_date - timedelta(days=370)
        actual_fetch_end_date = end_date + timedelta(days=2)

        logging.info(f"Fetching {index_ticker} data from {fetch_start_date_sma.strftime('%Y-%m-%d')} to {actual_fetch_end_date.strftime('%Y-%m-%d')}")
        index_data_full = yf.download(index_ticker, start=fetch_start_date_sma, end=actual_fetch_end_date, progress=True, auto_adjust=True)

        logging.info(f"Fetching {vix_ticker} data from {fetch_start_date_sma.strftime('%Y-%m-%d')} to {actual_fetch_end_date.strftime('%Y-%m-%d')}")
        vix_data_full = yf.download(vix_ticker, start=fetch_start_date_sma, end=actual_fetch_end_date, progress=True, auto_adjust=True)

        if index_data_full.empty:
            logging.error(f"Could not retrieve any market data for {index_ticker}.")
            return False
        if vix_data_full.empty:
            logging.warning(f"Could not retrieve any market data for {vix_ticker}. VIX data will be missing.")
            vix_data_full = pd.DataFrame(index=index_data_full.index, columns=['Close'])

        # Calculate both 50-day and 200-day SMAs
        index_data_full['SMA_50'] = index_data_full['Close'].rolling(window=50, min_periods=50).mean()
        index_data_full['SMA_200'] = index_data_full['Close'].rolling(window=200, min_periods=200).mean()

        index_data_selected = index_data_full[['Close', 'SMA_50', 'SMA_200']].copy()
        index_data_selected.rename(columns={'Close': f'{index_ticker}_Close', 'SMA_50': f'{index_ticker}_SMA_50', 'SMA_200': f'{index_ticker}_SMA_200'}, inplace=True)

        vix_data_selected = vix_data_full[['Close']].copy()
        vix_data_selected.rename(columns={'Close': f'{vix_ticker}_Close'}, inplace=True)

        merged_data = pd.merge(index_data_selected, vix_data_selected, left_index=True, right_index=True, how='outer')
        merged_data = merged_data[(merged_data.index >= pd.Timestamp(start_date)) & (merged_data.index <= pd.Timestamp(end_date))]

        if merged_data.empty:
            logging.warning(f"No data available for the specified range {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} after processing.")
            return False

        merged_data.index.name = 'Date'
        merged_data.to_csv(full_output_path)
        logging.info(f"Data successfully fetched and saved to {os.path.abspath(full_output_path)}")
        return True

    except Exception as e:
        logging.error(f"An error occurred during data fetching and preparation: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    req_start_date, req_end_date = get_valid_fetch_date_range()

    if req_start_date and req_end_date:
        # The function now uses the hardcoded directory by default
        if fetch_and_prepare_data(req_start_date, req_end_date):
            print("Data fetching process completed.")
        else:
            print("Data fetching process failed. Check logs for details.")
    else:
        print("Could not get valid date range for fetching. Exiting.")
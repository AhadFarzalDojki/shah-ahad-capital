import os
import yfinance as yf
import pandas as pd
from datetime import datetime
from pathlib import Path  # Import the Path library

# --- Configuration ---
STOCK_UNIVERSE = [
    'NVDA', 'INTC', 'AMCR', 'LCID', 'F', 'TSLA', 'WBD', 'AAPL', 'SOFI',
    'PLTR', 'AMD', 'GOOGL', 'AMZN', 'OSCR', 'VALE', 'BAC', 'PFE', 'RIG',
    'NU', 'AAL', 'BTG', 'QBTS', 'CNH', 'T', 'SMCI', # Original Symbols
    'CCL', 'HIMS', 'ABEV', 'SOUN', 'SNAP', 'RIOT', 'BBD', 'MARA', 'ACHR', # New from Yahoo
    'HOOD', 'CLSK', 'NKTR', 'PBR', 'UBER', 'GRAB', 'NIO', 'AVGO', 'APLD',
    'IREN', 'NGD', 'COIN', 'ITUB', 'RGTI', 'RKLB', 'NCLH', 'HBAN', 'XOM',
    'GGB', 'CMCSA', 'CLF', 'MU', 'CHWY', 'GOOG', 'RXRX', 'MRVL', 'AUR',
    'PCG', 'KGC', 'PSLV', 'JOBY', 'ZETA', 'SMR', 'AGNC', 'AG', 'QUBT',
    'ASTS', 'EQX', 'LYFT', 'MSFT', 'OKLO', 'OXY', 'IONQ', 'DOW', 'AES',
    'KEY', 'NOK', 'CSCO', 'NBIS', 'PONY', 'BB', 'WFC', 'PR', 'RIVN',
    'HAL', 'SLB', 'IAG', 'ERIC', 'ORCL', 'C', 'HL', 'ADT', 'HLN',
    'CLVT', 'AQN', 'BABA'
]

# --- MODIFICATION: Point to the Downloads folder ---
# 1. Find the path to your user's home directory
home_dir = Path.home()
# 2. Create the full path to a new folder inside your Downloads folder
OUTPUT_DIR = home_dir / 'Downloads' / 'stock_market_data'

# Date range for fetching data
START_DATE = '2010-01-01'
END_DATE = datetime.today().strftime('%Y-%m-%d')

# --- Main Download Logic ---
def download_all_stock_data():
    """
    Downloads historical data and saves it to a folder inside your Downloads.
    """
    # Create the output directory if it doesn't exist
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Created directory: {OUTPUT_DIR}")

    print(f"Starting download for {len(STOCK_UNIVERSE)} stocks...")
    
    for ticker in STOCK_UNIVERSE:
        # The os.path.join function works correctly with the Path object
        filepath = os.path.join(OUTPUT_DIR, f"{ticker}.csv")
        print(f"--- Downloading {ticker} ---")
        
        try:
            data = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
            
            if data.empty:
                print(f"WARNING: No data returned for {ticker}. Skipping.")
                continue
            
            data.to_csv(filepath)
            print(f"Successfully saved {ticker} data to {filepath}")
            
        except Exception as e:
            print(f"ERROR: Could not download or save data for {ticker}. Reason: {e}")

    print("\n--- Data download complete! ---")
    print(f"All available data is saved in: {OUTPUT_DIR}")

if __name__ == "__main__":
    download_all_stock_data()
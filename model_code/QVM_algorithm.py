import pandas as pd
import numpy as np
from scipy.stats import percentileofscore
import math
import xlsxwriter # Required by pandas to_excel for .xlsx
# Removed yfinance and datetime, timedelta as we're not fetching live data in this script

# --- CONFIGURATION ---
INPUT_CSV_FILE = 'kse100_financial_data_with_momentum.csv' # Data source
NUMBER_OF_STOCKS_TO_SELECT = 15 # Select top N stocks
MIN_MOMENTUM_METRICS_REQUIRED = 2 # Minimum number of momentum returns (out of 4) required for a stock to be considered

# --- HELPER FUNCTIONS ---

def portfolio_input_func():
    """Gets portfolio size from user input, ensuring it's a positive number."""
    while True:
        try:
            portfolio_size_str = input("Enter the value of your portfolio: ")
            portfolio_size = float(portfolio_size_str)
            if portfolio_size <= 0:
                print("Portfolio value must be greater than zero. Please try again.")
            else:
                return portfolio_size
        except ValueError:
            print("That's not a valid number. Please try again.")

# --- MAIN ALGORITHM LOGIC ---
def run_qvm_screener_from_csv():
    print(f"Loading stock data from '{INPUT_CSV_FILE}'...")
    try:
        df = pd.read_csv(INPUT_CSV_FILE)
    except FileNotFoundError:
        print(f"Error: The data file '{INPUT_CSV_FILE}' was not found.")
        print("Please ensure you have run the data generation script first and the file is in the correct directory.")
        return
    except Exception as e:
        print(f"Error loading CSV file: {e}")
        return

    if df.empty:
        print("The loaded CSV file is empty. Exiting.")
        return

    print(f"Successfully loaded {len(df)} stocks from CSV.")

    # --- Data Cleaning and Preprocessing ---
    print("\n--- Starting Data Cleaning and Preprocessing ---")

    # Columns expected from CSV for QVM
    # MODIFIED: Added 'P/S Ratio' to the list of value metrics
    required_value_metrics = ['P/E Ratio', 'P/B Ratio', 'P/S Ratio'] #Add & Enable EV/EBITDA for US stocks
    required_quality_metric = ['ROE']
    required_momentum_metrics = ['1M Return', '3M Return', '6M Return', '12M Return']
    essential_columns = ['Ticker', 'Price'] + required_value_metrics + required_quality_metric + required_momentum_metrics

    # Ensure correct data types for calculation (CSV might load them as objects if NaNs are strings like 'NaN')
    for col in ['Price'] + required_value_metrics + required_quality_metric + required_momentum_metrics:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        else:
            print(f"Warning: Expected column '{col}' not found in CSV. It will be treated as missing.")
            df[col] = np.nan # Add missing column filled with NaNs

    print(f"Initial number of stocks: {len(df)}")

    # 1. Filter out stocks with missing essential data like Price or Ticker
    df.dropna(subset=['Ticker', 'Price'], inplace=True)
    print(f"Stocks remaining after dropping those with no Ticker or Price: {len(df)}")
    if df['Price'].le(0).any(): # Check for non-positive prices
        df = df[df['Price'] > 0]
        print(f"Stocks remaining after dropping those with non-positive Price: {len(df)}")


    # 2. Filter for Value Metrics (P/E > 0, P/B > 0, P/S > 0, EV/EBITDA > 0)
    if 'P/E Ratio' in df.columns:
        df = df[df['P/E Ratio'] > 0]
    else:
        print("Warning: 'P/E Ratio' column not found. Stocks will not be filtered based on P/E > 0.")
    print(f"Stocks remaining after P/E Ratio > 0 filter: {len(df)}")

    if 'P/B Ratio' in df.columns:
        df = df[df['P/B Ratio'] > 0]
    else:
        print("Warning: 'P/B Ratio' column not found. Stocks will not be filtered based on P/B > 0.")
    print(f"Stocks remaining after P/B Ratio > 0 filter: {len(df)}")
    
    # NEW: Added filter for P/S Ratio
    if 'P/S Ratio' in df.columns:
        df = df[df['P/S Ratio'] > 0]
    else:
        print("Warning: 'P/S Ratio' column not found. Stocks will not be filtered based on P/S > 0.")
    print(f"Stocks remaining after P/S Ratio > 0 filter: {len(df)}")

    # if 'EV/EBITDA' in df.columns:
    #    df = df[df['EV/EBITDA'] > 0]
    #else:
    #    print("Warning: 'EV/EBITDA' column not found. Stocks will not be filtered based on EV/EBITDA > 0.")
    #print(f"Stocks remaining after EV/EBITDA > 0 filter: {len(df)}")
    
    # 3. Filter for Quality Metric (ROE must be present)
    if 'ROE' in df.columns:
        df.dropna(subset=['ROE'], inplace=True)
    else:
        print("Warning: 'ROE' column not found. Stocks will not be filtered based on ROE presence.")
    print(f"Stocks remaining after requiring ROE to be present: {len(df)}")

    # 4. Filter for Momentum Metrics (require at least MIN_MOMENTUM_METRICS_REQUIRED)
    if all(col in df.columns for col in required_momentum_metrics):
        df['valid_momentum_count'] = df[required_momentum_metrics].notna().sum(axis=1)
        df = df[df['valid_momentum_count'] >= MIN_MOMENTUM_METRICS_REQUIRED]
        df.drop(columns=['valid_momentum_count'], inplace=True) # Clean up helper column
    else:
        print("Warning: Not all momentum columns found. Stocks will not be filtered based on minimum momentum metrics.")
    print(f"Stocks remaining after requiring at least {MIN_MOMENTUM_METRICS_REQUIRED} momentum metrics: {len(df)}")


    if df.empty:
        print("No stocks remaining after data cleaning and filtering. Exiting.")
        return
    print("--- Data Cleaning and Preprocessing Complete ---")

    # --- Calculate Percentile Ranks for QVM Factors ---
    print("\nCalculating QVM percentiles...")
    # Value Metrics (lower is better, so 100 - percentile)
    if 'P/E Ratio' in df.columns and not df['P/E Ratio'].dropna().empty:
        df['P/E Percentile'] = df['P/E Ratio'].apply(lambda x: 100 - percentileofscore(df['P/E Ratio'].dropna(), x, kind='rank') if pd.notna(x) else np.nan)
    else:
        df['P/E Percentile'] = np.nan

    if 'P/B Ratio' in df.columns and not df['P/B Ratio'].dropna().empty:
        df['P/B Percentile'] = df['P/B Ratio'].apply(lambda x: 100 - percentileofscore(df['P/B Ratio'].dropna(), x, kind='rank') if pd.notna(x) else np.nan)
    else:
        df['P/B Percentile'] = np.nan
        
    # NEW: Added percentile calculation for P/S Ratio
    if 'P/S Ratio' in df.columns and not df['P/S Ratio'].dropna().empty:
        df['P/S Percentile'] = df['P/S Ratio'].apply(lambda x: 100 - percentileofscore(df['P/S Ratio'].dropna(), x, kind='rank') if pd.notna(x) else np.nan)
    else:
        df['P/S Percentile'] = np.nan

    if 'EV/EBITDA' in df.columns and not df['EV/EBITDA'].dropna().empty:
        df['EV/EBITDA Percentile'] = df['EV/EBITDA'].apply(lambda x: 100 - percentileofscore(df['EV/EBITDA'].dropna(), x, kind='rank') if pd.notna(x) else np.nan)
    else:
        df['EV/EBITDA Percentile'] = np.nan

    # Momentum Metrics (higher is better)
    for col_name, percentile_col_name in zip(required_momentum_metrics, ['1M Ret %ile', '3M Ret %ile', '6M Ret %ile', '12M Ret %ile']):
        if col_name in df.columns and not df[col_name].dropna().empty:
            df[percentile_col_name] = df[col_name].apply(lambda x: percentileofscore(df[col_name].dropna(), x, kind='rank') if pd.notna(x) else np.nan)
        else:
            df[percentile_col_name] = np.nan # If column missing or all NaN

    # Quality Metric (higher is better)
    if 'ROE' in df.columns and not df['ROE'].dropna().empty:
        df['ROE Percentile'] = df['ROE'].apply(lambda x: percentileofscore(df['ROE'].dropna(), x, kind='rank') if pd.notna(x) else np.nan)
    else:
        df['ROE Percentile'] = np.nan


    # --- Calculate Composite Factor Scores ---
    # MODIFIED: Added 'P/S Percentile' to the Value Score calculation
    df['Value Score'] = df[['P/E Percentile', 'P/B Percentile', 'P/S Percentile', 'EV/EBITDA Percentile']].mean(axis=1)
    df['Momentum Score'] = df[['1M Ret %ile', '3M Ret %ile', '6M Ret %ile', '12M Ret %ile']].mean(axis=1)
    df['Quality Score'] = df['ROE Percentile'] # Using single metric directly as score

    # --- Calculate Overall QVM Score ---
    # Equal weights for simplicity, can be adjusted:
    df['QVM Score'] = df[['Value Score', 'Momentum Score', 'Quality Score']].mean(axis=1)

    # --- Stock Selection ---
    # Drop stocks where QVM score could not be calculated (e.g., if all its components were NaN)
    df.dropna(subset=['QVM Score'], inplace=True)
    print(f"Stocks remaining after dropping those with no calculable QVM Score: {len(df)}")

    if df.empty:
        print("No stocks have a valid QVM score after calculations. Exiting.")
        return

    selected_stocks_df = df.sort_values(by='QVM Score', ascending=False)
    selected_stocks_df = selected_stocks_df.head(NUMBER_OF_STOCKS_TO_SELECT)

    if selected_stocks_df.empty:
        print("No stocks selected based on QVM score. Exiting.")
        return

    # --- Portfolio Allocation ---
    portfolio_size = portfolio_input_func()
    # Ensure len is not zero to prevent DivisionByZeroError, though previous checks should catch empty df
    if len(selected_stocks_df) == 0:
        print("No stocks selected, cannot calculate position size. Exiting.")
        return
    position_size = portfolio_size / len(selected_stocks_df)


    selected_stocks_df['Shares to Buy'] = selected_stocks_df['Price'].apply(
        lambda price: math.floor(position_size / price) if pd.notna(price) and price > 0 else 0
    )

    # --- Output to Excel ---
    # MODIFIED: Added 'P/S Ratio' to the report columns
    report_columns_base = [
        'Ticker', 'Price', 'QVM Score',
        'Value Score', 'P/E Ratio', 'P/B Ratio', 'P/S Ratio', 'EV/EBITDA',
        'Momentum Score', '1M Return', '3M Return', '6M Return', '12M Return',
        'Quality Score', 'ROE'
    ]
    report_columns_final = []
    for col in report_columns_base:
        if col in selected_stocks_df.columns:
            report_columns_final.append(col)
        else: # If a base column for report is somehow missing, add it with NaNs to avoid error
            selected_stocks_df[col] = np.nan 
            report_columns_final.append(col)
            print(f"Warning: Report column '{col}' was missing from selected stocks, added as NaN.")
            
    report_columns_final.append('Shares to Buy')


    final_report_df = selected_stocks_df[report_columns_final].reset_index(drop=True)

    excel_file_name = 'qvm_strategy_trades_from_csv.xlsx'
    try:
        writer = pd.ExcelWriter(excel_file_name, engine='xlsxwriter')
        final_report_df.to_excel(writer, sheet_name='QVM Trades', index=False)

        workbook = writer.book
        worksheet = writer.sheets['QVM Trades']

        header_format = workbook.add_format({
            'bold': True, 'text_wrap': True, 'valign': 'top',
            'fg_color': '#D7E4BC', 'border': 1, 'align': 'center'
        })
        dollar_format = workbook.add_format({'num_format': '$#,##0.00', 'align': 'right'})
        ratio_format = workbook.add_format({'num_format': '#,##0.00', 'align': 'right'})
        percent_format = workbook.add_format({'num_format': '0.00%', 'align': 'right'})
        integer_format = workbook.add_format({'num_format': '#,##0', 'align': 'right'})
        score_format = workbook.add_format({'num_format': '#,##0.0', 'align': 'right'})

        for col_num, value in enumerate(final_report_df.columns.values):
            worksheet.write(0, col_num, value, header_format)

        # Apply column formats based on column names for more robustness
        for col_num, col_name in enumerate(final_report_df.columns):
            if col_name == 'Price':
                worksheet.set_column(col_num, col_num, 10, dollar_format)
            elif col_name in ['QVM Score', 'Value Score', 'Momentum Score', 'Quality Score']:
                worksheet.set_column(col_num, col_num, 12, score_format)
            # MODIFIED: Added 'P/S Ratio' to the ratio format list
            elif col_name in ['P/E Ratio', 'P/B Ratio', 'P/S Ratio', 'EV/EBITDA']:
                worksheet.set_column(col_num, col_num, 10, ratio_format)
            elif col_name in ['1M Return', '3M Return', '6M Return', '12M Return', 'ROE']:
                worksheet.set_column(col_num, col_num, 10, percent_format)
            elif col_name == 'Shares to Buy':
                worksheet.set_column(col_num, col_num, 12, integer_format)
            elif col_name == 'Ticker':
                 worksheet.set_column(col_num, col_num, 10) # Default for Ticker
            else: # Default for any other unexpected columns
                worksheet.set_column(col_num, col_num, 10)


        # Auto-adjust column widths as a final touch (can override above if not careful with order)
        # More robust auto-width:
               # Auto-adjust column widths
        for i, col_name in enumerate(final_report_df.columns):
            # Calculate the maximum length of the data in the column
            try:
                # Ensure data is string to measure length, handle potential non-string data
                max_data_len = final_report_df[col_name].astype(str).map(len).max()
            except TypeError: # Handles cases where astype(str) might fail for complex objects (unlikely here)
                max_data_len = 0 
            
            header_len = len(col_name)
            # Set the column width to the maximum of header length or data length, plus a little padding
            # Cap the width at 50 to prevent extremely wide columns
            column_width = min(max(max_data_len, header_len) + 2, 50)
            
            # Check if a specific format was already applied that set a width
            # This part is tricky as xlsxwriter doesn't easily expose the width set by add_format() on set_column()
            # For simplicity, we will let this new auto-width override previous themed widths if it's larger,
            # or if the themed width was smaller than a reasonable default.
            
            # Get the width that might have been set by the specific format section above
            # This requires inspecting the internal _colinfo if it exists and the column index is in it
            current_theme_width = 0
            if hasattr(worksheet, '_colinfo') and i in worksheet._colinfo:
                 col_info_obj = worksheet._colinfo[i]
                 if hasattr(col_info_obj, 'width_px') and worksheet.default_char_width > 0: # width_px is more reliable if present
                     # Convert pixel width to character width approximately
                     current_theme_width = col_info_obj.width_px / worksheet.default_char_width
                 elif hasattr(col_info_obj, 'width'): # Fallback to width if width_px not there
                     current_theme_width = col_info_obj.width


            # If the auto-calculated width is greater than the theme-set width, or if theme width is very small, use auto-width.
            # Otherwise, the theme-set width (e.g., for Price, Score) might be preferable if it's already generous.
            if column_width > current_theme_width or current_theme_width < 5: # Prioritize larger auto-width or if theme width is too small
                worksheet.set_column(i, i, column_width)
            elif current_theme_width > 0: # If theme width exists and is reasonable, keep it
                 worksheet.set_column(i, i, current_theme_width)
            # If no theme width and column_width is not greater, it means column_width might be smaller than
            # current_theme_width (which is 0), so set_column(column_width) is still needed.
            # The condition `if column_width > current_theme_width` already covers this if current_theme_width is 0.

        writer.close()
        print(f"\nBlended QVM Strategy analysis complete. Report saved to '{excel_file_name}'")
        print("\nSelected Stocks:")
        print(final_report_df)
    except Exception as e:
        print(f"Error writing to Excel file: {e}")


if __name__ == '__main__':
    run_qvm_screener_from_csv()
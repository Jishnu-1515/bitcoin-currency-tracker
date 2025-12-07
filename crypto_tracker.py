from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import time
import argparse
import os
from datetime import datetime
import sys

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

from pathlib import Path
import ctypes
from uuid import UUID
from ctypes import wintypes

def get_downloads_folder():
    """
    Returns the actual Downloads folder, even if user moved it to D: or elsewhere.
    Works on Windows. Falls back to ~/Downloads on other OS.
    """
    if os.name == "nt":
       
        _SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
        _SHGetKnownFolderPath.argtypes = [
            ctypes.c_void_p,   
            wintypes.DWORD,   
            wintypes.HANDLE,   
            ctypes.POINTER(ctypes.c_wchar_p) 
        ]
        _SHGetKnownFolderPath.restype = wintypes.HRESULT

        fid = UUID("{374DE290-123F-4565-9164-39C4925E467B}").bytes_le
        pPath = ctypes.c_wchar_p()

        hresult = _SHGetKnownFolderPath(fid, 0, 0, ctypes.byref(pPath))
        if hresult == 0 and pPath.value:
            return Path(pPath.value)

 
    return Path.home() / "Downloads"



def create_driver(headless: bool = False, window_size: str = "1920,1080"):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument(f"--window-size={window_size}")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option('excludeSwitches', ['enable-logging'])

    driver = webdriver.Chrome(options=options)
    return driver


def parse_row_cells(cells):
    name = ''
    price = ''
    change_24h = ''
    market_cap = ''

    texts = [c.strip() for c in cells]

   
    try:
        if len(texts) >= 4:
        
            for idx in (1, 2, 0):
                candidate = texts[idx]
                if candidate and any(ch.isalpha() for ch in candidate):
                    name = candidate.split('\n')[0]
                    break
            
            for idx in (2, 3, 4):
                if idx < len(texts) and '$' in texts[idx]:
                    price = texts[idx].split('\n')[0]
                    break
            
            for idx in (3, 4, 5):
                if idx < len(texts) and '%' in texts[idx]:
                    change_24h = texts[idx].split('\n')[0]
                    break
            
            for idx in (6, 7, 5):
                if idx < len(texts) and ('$' in texts[idx] or 'M' in texts[idx] or 'B' in texts[idx]):
                    market_cap = texts[idx].split('\n')[0]
                    break
    except Exception:
        pass

 
    if not price or '$' not in price:
        for t in texts:
            if '$' in t and len(t) < 20:
                price = t.split('\n')[0]
                break

    if not change_24h or '%' not in change_24h:
        for t in texts:
            if '%' in t and (t.count('%') == 1):
                change_24h = t.split('\n')[0]
                break

    if not market_cap or ('$' not in market_cap and 'B' not in market_cap and 'M' not in market_cap):
        dollar_candidates = [t for t in texts if '$' in t and len(t) > 5]
        if dollar_candidates:
            market_cap = dollar_candidates[-1].split('\n')[0]

    name = name or (texts[0] if texts else '')
    return name, price, change_24h, market_cap


def scrape_top_n(driver, top_n=10, wait_seconds=15):
    url = 'https://coinmarketcap.com/'
    driver.get(url)

    wait = WebDriverWait(driver, wait_seconds)
    rows = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//table//tbody/tr")))

    data = []
    count = min(top_n, len(rows))
    for i in range(count):
        row = rows[i]
        try:
            td_elements = row.find_elements(By.TAG_NAME, 'td')
            td_texts = [td.text for td in td_elements]
            name, price, change_24h, market_cap = parse_row_cells(td_texts)

            price = price.replace('\n', ' ').strip()
            change_24h = change_24h.replace('\n', ' ').strip()
            market_cap = market_cap.replace('\n', ' ').strip()

            data.append({
                'rank': i + 1,
                'name': name,
                'price': price,
                '24h_change': change_24h,
                'market_cap': market_cap,
            })
        except Exception as e:
            print(f"Warning: failed to parse row {i+1}: {e}", file=sys.stderr)
    return data


def append_to_csv(data, output_path):
    df = pd.DataFrame(data)
    if df.empty:
        print('No data to write.')
        return
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    df['scrape_utc'] = timestamp

    write_header = not os.path.exists(output_path) or os.path.getsize(output_path) == 0
    df.to_csv(output_path, mode='a', index=False, header=write_header)
    print(f'Appended {len(df)} rows to {output_path} (UTC {timestamp})')


def main():
    parser = argparse.ArgumentParser(description='Cryptocurrency Price Tracker (Selenium)')
    parser.add_argument('--headless', action='store_true', help='Run Chrome in headless mode')
    parser.add_argument('--top', type=int, default=10, help='Number of top coins to scrape (default 10)')
    parser.add_argument('--output', type=str, default='crypto_prices.csv', help='CSV output file path')
    parser.add_argument('--min-price', type=float, default=None, help='Optional: only include coins with price >= this USD value')
    parser.add_argument('--wait', type=int, default=15, help='Max wait time (seconds) for page load')
    args = parser.parse_args()

    driver = None
    try:
        print('Starting Chrome WebDriver...')
        driver = create_driver(headless=args.headless)
        print('Scraping CoinMarketCap...')
        data = scrape_top_n(driver, top_n=args.top, wait_seconds=args.wait)

        if args.min_price is not None:
            filtered = []
            for row in data:
                price_str = row['price']
                price_num = None
                try:
                    cleaned = price_str.replace('$', '').replace(',', '').split()[0]
                    price_num = float(cleaned)
                except Exception:
                    price_num = None
                if price_num is not None and price_num >= args.min_price:
                    filtered.append(row)
            data = filtered

        append_to_csv(data, args.output)

    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)
    finally:
        if driver:
            driver.quit()



def launch_ui():
    root = tk.Tk()
    root.title("Cryptocurrency Price Tracker")
    root.geometry("950x550")
    root.configure(bg="#000000")  

  
    title_label = tk.Label(
        root,
        text="Crypto Price Tracker",
        font=("Poppins", 22, "bold"),
        fg="#FFFFFF", 
        bg="#000000"
    )
    title_label.pack(pady=12)


    table_frame = ttk.Frame(root)
    table_frame.pack(pady=10, fill="both", expand=True)

   
    style = ttk.Style()
    style.theme_use("clam")

    style.configure("Treeview",
        background="#121212",
        foreground="#E5E5E5",
        rowheight=30,
        fieldbackground="#121212",
        font=("Poppins", 11)
    )

    style.configure("Treeview.Heading",
        background="#1F1F1F",
        foreground="#FF0000",  
        relief="flat",
        font=("Poppins", 13, "bold")
    )

    style.map("Treeview",
        background=[("selected", "#00FFBF")],
        foreground=[("selected", "black")]
    )

    columns = ("Rank", "Name", "Price", "24h Change", "Market Cap")
    tree = ttk.Treeview(table_frame, columns=columns, show="headings")

    for col in columns:
        tree.heading(col, text=col)
        tree.column(col, anchor=tk.CENTER, width=180)

    tree.pack(fill="both", expand=True)

   
    def fetch_and_display():
        tree.delete(*tree.get_children())
        try:
            driver = create_driver(headless=True)
            data = scrape_top_n(driver, top_n=10)
            driver.quit()

            if not data:
                messagebox.showwarning("No Data", "Failed to scrape data.")
                return

            downloads_dir = get_downloads_folder()
            downloads_path = str(downloads_dir / "crypto_prices_ui.csv")
            append_to_csv(data, downloads_path)


            for row in data:
                tree.insert("", tk.END, values=(
                    row['rank'],
                    row['name'],
                    row['price'],
                    row['24h_change'],
                    row['market_cap']
                ))

            messagebox.showinfo("Success", "Data Updated Successfully!\n Check your downloads folder!")
        except Exception as e:
            messagebox.showerror("Error", str(e))

  
    fetch_btn = tk.Button(
        root,
        text="Fetch Live Prices",
        font=("Poppins", 14, "bold"),
        fg="black",
        bg="#FF0000",
        activebackground="#DC143C",
        cursor="hand2",
        width=18,
        command=fetch_and_display
    )
    fetch_btn.pack(pady=12)

    root.mainloop()



if __name__ == "__main__":
    
    launch_ui()
   

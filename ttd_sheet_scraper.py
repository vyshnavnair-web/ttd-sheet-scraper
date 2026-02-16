import time
import datetime
import random
import gspread
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURATION ---
SHEET_NAME = "TTD-Automations" 
JSON_KEY_FILE = 'service_account.json'

def setup_scraper():
    chrome_options = Options()
    # Using 'headless=new' is critical for avoiding bot detection
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--lang=en-US")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # --- STEALTH SETTINGS ---
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    # Remove the 'webdriver' fingerprint
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    
    return driver

def check_place_on_maps(driver, place_id):
    # Some Place IDs work better with the direct /maps/place/ search URL
    url = f"https://www.google.com/maps/search/?api=1&query=google&query_place_id={place_id}"
    try:
        driver.get(url)
        
        # 1. Wait for the main container to load
        # Increased timeout to 15s to account for slow lazy-loading
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//h1")))
        
        # 2. Variable sleep: Google Maps loads modules at different speeds
        time.sleep(random.uniform(4, 6)) 

        # 3. Keyword Check (Expanded list)
        keywords = ["Tickets", "Admissions", "Tours", "Activities", "Book a tour", "Admission"]
        found = []
        
        # Search the whole page source for keywords if they aren't in specific elements
        for word in keywords:
            # Look for text in buttons, spans, or labels
            xpath = f"//*[contains(text(), '{word}') or contains(@aria-label, '{word}')]"
            if driver.find_elements(By.XPATH, xpath):
                found.append(word)

        if found:
            return "YES", ", ".join(set(found))
        return "NO", "Not detected"
        
    except Exception as e:
        return "ERROR", str(e)[:50]

def run_automation():
    print("Connecting to Google Sheets...")
    try:
        gc = gspread.service_account(filename=JSON_KEY_FILE)
        sh = gc.open(SHEET_NAME)
        worksheet = sh.get_worksheet(0)
    except Exception as e:
        print(f"Failed to connect to Sheets: {e}")
        return

    # Fetch all Place IDs from Column A (ignoring header)
    all_pids = worksheet.col_values(1)[1:] 
    
    print(f"Starting browser. Processing {len(all_pids)} places.")
    driver = setup_scraper()

    try:
        for index, pid in enumerate(all_pids):
            # Calculate the actual row in the Google Sheet
            row_idx = index + 2 
            
            print(f"Checking {row_idx-1}/{len(all_pids)}: {pid}")
            
            status, details = check_place_on_maps(driver, pid)
            
            # Update the Sheet
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            worksheet.update_cell(row_idx, 2, status)   # Col B
            worksheet.update_cell(row_idx, 3, details)  # Col C
            worksheet.update_cell(row_idx, 4, current_time) # Col D
            
            print(f"   -> Result: {status}")
            
            # CRITICAL: Random wait between requests to prevent mass-blocking
            if index < len(all_pids) - 1:
                sleep_time = random.uniform(6, 12)
                print(f"   -> Waiting {sleep_time:.1f}s...")
                time.sleep(sleep_time)

    finally:
        driver.quit()
        print("\n✅ Process complete. Sheet updated.")

if __name__ == "__main__":
    run_automation()
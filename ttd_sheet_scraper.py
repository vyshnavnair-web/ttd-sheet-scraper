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

# --- COLUMN MAPPING ---
COL_CE_ID       = 1  # Col A
COL_CE_NAME     = 2  # Col B
COL_PLACE_ID    = 3  # Col C
COL_TTD_STATUS  = 4  # Col D - YES/NO result
COL_TTD_DETAILS = 5  # Col E - keywords found
COL_TIMESTAMP   = 6  # Col F - last checked
COL_RUN_STATUS  = 7  # Col G - "Success" once completed

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
    url = f"https://www.google.com/maps/search/?api=1&query=google&query_place_id={place_id}"
    try:
        driver.get(url)

        # Wait for h1 to confirm page loaded
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//h1"))
        )

        # --- GOOGLE BLOCKING DETECTION ---
        # Check for CAPTCHA, consent pages, or empty/error pages
        page_source = driver.page_source.lower()
        page_title = driver.title.lower()
        blocking_signals = ["captcha", "consent", "before you continue", "unusual traffic", "verify you're human"]
        for signal in blocking_signals:
            if signal in page_source or signal in page_title:
                return "BLOCKED", f"Google blocking detected: {signal}"

        # Also check that the h1 actually has a place name (not an error page)
        h1_text = driver.find_element(By.XPATH, "//h1").text.strip()
        if not h1_text:
            return "ERROR", "Page loaded but h1 is empty — possible bot block"

        # Human-like pause before interacting
        time.sleep(random.uniform(1.5, 3.0))

        # --- CLICK TICKETS TAB ---
        # Use role="tab" + text to avoid matching "Tickets" elsewhere on page
        try:
            tickets_tab = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((
                    By.XPATH, "//button[@role='tab' and contains(., 'Tickets')]"
                ))
            )
            driver.execute_script("arguments[0].click();", tickets_tab)
            time.sleep(random.uniform(1.5, 2.5))
        except:
            return "NO", "No Tickets tab found"

        # --- DETECT TTD SECTIONS ---
        sections_found = []

        # CHECK 1: Admission
        # Primary: official Google TTD image - hardcoded asset, only appears in Admission module
        admission_image = driver.find_elements(
            By.XPATH, "//img[contains(@src, 'official_admission_32x32.png')]"
        )
        # Backup: Admission sub-tab button
        admission_tab = driver.find_elements(
            By.XPATH, "//button[@role='tab' and contains(., 'Admission')]"
        )
        if admission_image or admission_tab:
            sections_found.append("Admission")

        # CHECK 2: Tours & Activities sub-tab button
        tours_tab = driver.find_elements(
            By.XPATH, "//button[@role='tab' and contains(., 'Tours')]"
        )
        if tours_tab:
            sections_found.append("Tours & Activities")

        if sections_found:
            return "YES", ", ".join(sections_found)
        return "NO", f"Tickets tab found but no modules detected (h1: {h1_text[:30]})"

    except Exception as e:
        return "ERROR", str(e)[:80]

def run_automation():
    print("Connecting to Google Sheets...")
    try:
        gc = gspread.service_account(filename=JSON_KEY_FILE)
        sh = gc.open(SHEET_NAME)
        worksheet = sh.get_worksheet(0)
    except Exception as e:
        print(f"Failed to connect to Sheets: {e}")
        return

    # Fetch all rows (ignoring header)
    all_rows = worksheet.get_all_values()[1:]

    # Filter: only rows where Col C (Place ID) is not empty AND Col G (Run Status) != "Success"
    rows_to_process = []
    for index, row in enumerate(all_rows):
        # Pad row in case some trailing columns are missing
        while len(row) < COL_RUN_STATUS:
            row.append("")

        place_id   = row[COL_PLACE_ID - 1].strip()
        run_status = row[COL_RUN_STATUS - 1].strip()

        if place_id and run_status.lower() != "success":
            rows_to_process.append((index + 2, place_id))  # +2 for 1-index + header

    if not rows_to_process:
        print("✅ Nothing to process — all rows are already marked Success.")
        return

    print(f"Starting browser. Processing {len(rows_to_process)} rows (skipping already completed).")
    driver = setup_scraper()

    try:
        for i, (row_idx, pid) in enumerate(rows_to_process):
            print(f"Checking {i+1}/{len(rows_to_process)} (Sheet row {row_idx}): {pid}")
            
            ttd_status, details = check_place_on_maps(driver, pid)
            
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            worksheet.update_cell(row_idx, COL_TTD_STATUS,  ttd_status)    # Col D
            worksheet.update_cell(row_idx, COL_TTD_DETAILS, details)        # Col E
            worksheet.update_cell(row_idx, COL_TIMESTAMP,   current_time)   # Col F
            worksheet.update_cell(row_idx, COL_RUN_STATUS,  "Success")      # Col G

            print(f"   -> Result: {ttd_status} | Run Status: Success")
            
            # Random wait between requests to prevent mass-blocking
            if i < len(rows_to_process) - 1:
                sleep_time = random.uniform(6, 12)
                print(f"   -> Waiting {sleep_time:.1f}s...")
                time.sleep(sleep_time)

    finally:
        driver.quit()
        print("\n✅ Process complete. Sheet updated.")

if __name__ == "__main__":
    run_automation()

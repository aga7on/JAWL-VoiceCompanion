from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

opts = Options()
opts.add_argument("--start-maximized")
driver = webdriver.Chrome(options=opts)
driver.get("https://www.youtube.com/watch?v=GXe8XEFA9Pc")
time.sleep(2)

pos = driver.get_window_position()
size = driver.get_window_size()
title = driver.title
print(f"Chrome position: {pos}")
print(f"Chrome size: {size}")
print(f"Chrome title: {title}")

# Check which monitor Chrome is on:
# If x >= 1920, it is on Monitor 2 (Device 1).
# If x < 1920, it is on Monitor 1 (Device 0).

driver.quit()

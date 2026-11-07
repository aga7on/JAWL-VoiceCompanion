from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

opts = Options()
opts.add_argument("--headless=new")
d = webdriver.Chrome(options=opts)
try:
    d.get("https://www.youtube.com/watch?v=GXe8XEFA9Pc")
    time.sleep(3)
    dur = d.execute_script("var v = document.querySelector('video'); return v ? v.duration : 0.0;")
    title = d.title
    print(f"Title: {title}")
    print(f"Total Duration: {dur} seconds ({dur/60:.2f} minutes)")
finally:
    d.quit()

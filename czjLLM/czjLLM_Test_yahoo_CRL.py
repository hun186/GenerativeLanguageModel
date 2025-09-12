from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# 設定瀏覽器驅動，這裡以Chrome為例
driver = webdriver.Chrome()

# 目標網頁URL
url = "https://tw.sports.yahoo.com/news/"

# 訪問網頁
driver.get(url)

# 等待網頁載入，並確認頁面元素
try:
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//*[@id='content']"))
    )

    # 使用XPath抓取所有新聞標題
    titles = driver.find_elements_by_xpath("//*[@id='content']//h1")
    for title in titles:
        print(title.text)

except Exception as e:
    print(e)

finally:
    driver.quit()
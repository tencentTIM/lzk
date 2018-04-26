# -*- coding: utf-8 -*-
"""
Created on Sun Apr  1 10:18:42 2018

@author: lzk95
"""
# -*- coding:utf-8 -*-
#!/usr/bin/env python3
import time
import os
import re
from bs4 import BeautifulSoup
from urllib.request import urlopen
from selenium import webdriver
import pymongo
from pymongo import MongoClient
import hashlib
from collections import deque
from lxml import etree
import threading

# 数据库的准备，这里用的是mongodb；
client = MongoClient('localhost',27017)
db = client.test
followers = db.followers

# 注意：这里如果不设置user-agent，可能是无法跳转的
user_agent = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_4) " +
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/29.0.1547.57 Safari/537.36"
)

# 基本参数的一些准备工作
parser = 'html5lib'
domain = "weibo.com"
url_home = "http://" + domain
downloaded_bf = deque()              # 双向队列，用于保证多线程爬取是安全的
cur_queue = deque()
min_mblogs_allowed = 15              # 爬取的阈值设置
max_follow_fans_ratio_allowed = 2


# 这里有两个爬虫，一个爬取微博数据，一个爬取用户数据
weibo_driver = webdriver.Firefox()  # 微博爬虫
weibo_driver.set_window_size(1920, 1200)  # optional
user_driver = webdriver.Firefox()   # user crawler
user_driver.set_window_size(1920, 1200)


# url入队列，当然，入队列前要先做查重	
def enqueueUrl(url):
    try:
        md5v = hashlib.md5(url).hexdigest()
        if md5v not in downloaded_bf: # 去重
            print(url + ' is added to queue')
            cur_queue.append(url)
            downloaded_bf.append(md5v)
        else:
            print('Skip %s'%(url))
    except ValueError:
        pass

# 队列左端弹出一个值
def dequeuUrl():
    return cur_queue.popleft()

# 到下一页取抓取		
def go_next_page(cur_driver):
    try:
        next_page = cur_driver.find_element_by_xpath('//a[contains(@class, "page next")]').get_attribute('href')
        print('next page is ' + next_page)
        cur_driver.get(next_page)
        time.sleep(3)
        return True
    except Exception:
        print('next page is not found')
        return False

# 通过xpath尝试获取元素，最多尝试6次	
def get_element_by_xpath(cur_driver, path):
    tried = 0
    while tried < 6:
        html = cur_driver.page_source
        tr = etree.HTML(html)
        elements = tr.xpath(path)
        if len(elements) == 0:
            time.sleep(1)
            continue
        return elements

# 滚屏，保证能抓到数据			
def scroll_to_bottom():
    # 最多尝试 20 次滚屏
    print('scroll down')
    for i in range(0,20):
        # print 'scrolling for the %d time' % (i)
        weibo_driver.execute_script('window.scrollTo(0, document.body.scrollHeight)')
        html = weibo_driver.page_source
        tr = etree.HTML(html)
        next_page_url = tr.xpath('//a[contains(@class,"page next")]')
        if len(next_page_url) > 0:
            return next_page_url[0].get('href')
        if len(re.findall('点击重新载入', html)) > 0:
            print('scrolling failed, reload it')
            weibo_driver.find_element_by_link_text('点击重新载入').click()
        time.sleep(1)

# 提取用户信息
def extract_user(users):
    print('extract user')
    for i in range(0,20):
        for user_element in user_driver.find_elements_by_xpath('//*[contains(@class, "follow_item")]'):
            tried = 0
            while tried < 3:
                try:
                    user = {}
                    user['follows'] = re.findall('(\d+)', user_element.find_element_by_xpath('.//div[@class="info_connect"]/span').text)[0]
                    user['follows_link'] = user_element.find_element_by_xpath('.//div[@class="info_connect"]/span//a').get_attribute('href')
                    user['fans'] = re.findall('(\d+)', user_element.find_elements_by_xpath('.//div[@class="info_connect"]/span')[1].text)[0]
                    user['fans_link'] = user_element.find_elements_by_xpath('.//div[@class="info_connect"]/span//a')[1].get_attribute('href')
                    user['mblogs'] = re.findall('(\d+)', user_element.find_elements_by_xpath('.//div[@class="info_connect"]/span')[2].text)[0]
                    user_link = user_element.find_element_by_xpath('.//div[contains(@class,"info_name")]/a')
                    user['link'] = re.findall('(.+)\?', user_link.get_attribute('href'))[0]
                    if user['link'][:4] != 'http':
                        user['link'] = domain + user['link']
                    user['name'] = user_link.text
                    user['icon'] = re.findall('/([^/]+)$', user_element.find_element_by_xpath('.//dt[@class="mod_pic"]/a/img').get_attribute('src'))[0]
                    # name = user_element.find_element_by_xpath('.//a[@class="S_txt1"]')

                    print('--------------------')
                    print(user['name'] + ' follows: ' + user['follows'] + ' blogs:' + user['mblogs'])
                    print(user['link'])

                    # 如果微博数量少于阈值或者关注数量与粉丝数量比值超过阈值，则跳过
                    if int(user['mblogs']) < min_mblogs_allowed or int(user['follows'])/int(user['fans']) > max_follow_fans_ratio_allowed:
                        break

                    enqueueUrl(user['link'])
                    users.append(user)
                    break
                except Exception:
                    time.sleep(1)
                    tried += 1
		# 用户页面的翻页
        if go_next_page(user_driver) is False:
            return users
    return users

# 提取微博数据
def extract_feed(feeds):
    for i in range(0,20):
	# 只有在抓取微博数据时需要滚屏
        scroll_to_bottom()
        for element in weibo_driver.find_elements_by_class_name('WB_detail'):
            tried = 0
            while tried < 3:
                try:
                    feed = {}
                    feed['time'] = element.find_element_by_xpath('.//div[@class="WB_from S_txt2"]').text
                    feed['content'] = element.find_element_by_class_name('WB_text').text
                    feed['image_names'] = []
                    for image in element.find_elements_by_xpath('.//li[contains(@class,"WB_pic")]/img'):
                        feed['image_names'].append(re.findall('/([^/]+)$', image.get_attribute('src')))
                    feeds.append(feed)
                    print('--------------------')
                    print(feed['time'])
                    print(feed['content'])
                    break
                except Exception:
                    tried += 1
                    time.sleep(1)
		# 微博信息的下一页
        if go_next_page(weibo_driver) is False:
            return feeds

# 获取用户关注的人
def getFollows(pageInfo):
    pattern3 = re.compile('class="S_txt1" title="(.*?)".*?usercard')
    follows = re.findall(pattern3, pageInfo)
    print(follows)
    for i in follows:
        print(i)
        follower = {"name":i,"type":"follower"}
        rs = followers.insert_one(follower)
        print('one insert:{0}'.format(rs.inserted_id))
    
    patterUrls = re.compile('<a bpfilter="page" class="page S_txt1"[\s\S]*?href="([\s\S]*?pids=Pl_Official_RelationMyfollow__92&amp;cfs=&amp;Pl_Official_RelationMyfollow__92_page=[\s\S]*?)"')
    follows = re.findall(patterUrls, pageInfo)
    for i in follows:
        print("http://weibo.com/"+i)

# 登录逻辑，有待完善		
def login(current_driver,username, password):
    current_driver.get(url_home)  #访问目标网页地址
    time.sleep(8)

    # 登录
    current_driver.find_element_by_id('loginname').send_keys(username)
    current_driver.find_element_by_xpath('/html/body/div[1]/div[1]/div/div[2]/div[1]/div[2]/div/div[2]/div[1]/div[2]/div[1]/div/div/div/div[3]/div[2]/div/input').send_keys(password)
    # 执行 click()
    current_driver.find_element_by_xpath('//div[contains(@class,"login_btn")][1]/a').click()
    time.sleep(8)
    current_driver.save_screenshot("weiboLogin.png")

	# 验证码的处理
    ##verifyCode = input("Please input verify code:")            
    ##user_driver.find_element_by_xpath('/html/body/div[1]/div[1]/div/div[2]/div[1]/div[2]/div/div[2]/div[1]/div[2]/div[1]/div/div/div/div[3]/div[3]/div/input').send_keys(verifyCode)
    ##user_driver.find_element_by_xpath('//div[contains(@class,"login_btn")][1]/a').click()
    ##time.sleep(8)
    ##user_driver.save_screenshot("weiboLogin2.png")
    
def main(username, password):
    # 登录
    login(user_driver,username, password)
    login(weibo_driver,username, password)
    
    # 等会操作
    time.sleep(30)
    #user_driver.save_screenshot("weibo.png")
    
    ## 获取用户本身的数据信息
    pattern = re.compile('<strong node-type="follow">(\d*?)</strong>')
    items = re.findall(pattern, user_driver.page_source)
    for i in items:
        print(i)

    pattern2 = re.compile('<a bpfilter="page_frame" href="(/\d*?/follow.*?)".*?</a>')
    urlSubscribeds = re.findall(pattern2, user_driver.page_source)
    ##urlSubscribeds = user_driver.find_element_by_xpath('//a[@class="S_txt1"]').get_attribute('href')
    print("urlSubscribeds[0]: ",urlSubscribeds[0])
    user_driver.get("http://weibo.com/"+urlSubscribeds[0])
    time.sleep(10)
    user_driver.save_screenshot("weiboMyFollowersPage.png")
    getFollows(user_driver.page_source)
   
    # 通过一个大V,比如王思聪的微博，进入有价值的关注点，再进行抓取
    #user_driver.get("https://weibo.com/sephirex?refer_flag=1001030101_")
    # 等会操作
    #time.sleep(20)
    #user_driver.save_screenshot("weiboGetF.png")
    
    ## 从大V的入口进去爬取,真正的URL入口
    user_link = "https://weibo.com/yaochen?refer_flag=1001030101_&is_all=1"
    print('downloading ' + user_link)
    weibo_driver.get(user_link)
    time.sleep(5)
    
    # 提取用户姓名
    account_name = get_element_by_xpath(weibo_driver, '//h1')[0].text
    photo = get_element_by_xpath(weibo_driver, '//p[@class="photo_wrap"]/img')[0].get('src')
    account_photo = re.findall('/([^/]+)$', photo)
    # 提取他的关注主页
    follows_link = get_element_by_xpath(weibo_driver, '//a[@class="t_link S_txt1"]')[0].get('href')
    print('account: ' + account_name)
    print('account_photo: '+account_photo[0])
    print('follows link is ' + follows_link)

    #user_driver.get("http"+follows_link)
    feeds = []
    #users = []
	# 起一个线程取获取微博数据
	# TODO:这里需要再起一个抓取用户数据的线程，注意协调两个线程的关系
    t_feeds = threading.Thread(target=extract_feed, name=None, args=(feeds,))
    t_feeds.start()
    t_feeds.join()
    if __name__ == '__main__':
      login(weibo_driver,username, password)

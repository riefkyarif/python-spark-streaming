import socket
import sys
import requests
import requests_oauthlib
import json

# Replace the values below with yours
ACCESS_TOKEN = 'YOUR_ACCESS_TOKEN'
ACCESS_SECRET = 'YOUR_ACCESS_SECRET'
CONSUMER_KEY = 'YOUR_CONSUMER_KEY'
CONSUMER_SECRET = 'YOUR_CONSUMER_SECRET'
my_auth = requests_oauthlib.OAuth1(CONSUMER_KEY, CONSUMER_SECRET,ACCESS_TOKEN, ACCESS_SECRET)

def get_tweets():
	url = 'https://stream.twitter.com/1.1/statuses/filter.json'
	query_data = [('language', 'en'), ('locations', '-130,-20,100,50'),('track','#')]
	query_url = url + '?' + '&'.join([str(t[0]) + '=' + str(t[1]) for t in query_data])
	response = requests.get(query_url, auth=my_auth, stream=True)
	print(query_url, response)
	return response
	
def send_tweets_to_spark(http_resp, tcp_connection):
	for line in http_resp.iter_lines():
    	try:
        	full_tweet = json.loads(line)
        	tweet_text = full_tweet['text']
        	print("Tweet Text: " + tweet_text)
        	print ("------------------------------------------")
        	tcp_connection.send(tweet_text + '\n')
    	except:
        	e = sys.exc_info()[0]
        	print("Error: %s" % e)
        	
        	TCP_IP = "localhost"
TCP_PORT = 9009
conn = None
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind((TCP_IP, TCP_PORT))
s.listen(1)
print("Waiting for TCP connection...")
conn, addr = s.accept()
print("Connected... Starting getting tweets.")
resp = get_tweets()
send_tweets_to_spark(resp, conn)


from pyspark import SparkConf,SparkContext
from pyspark.streaming import StreamingContext
from pyspark.sql import Row,SQLContext
import sys
import requests


# create spark configuration
conf = SparkConf()
conf.setAppName("TwitterStreamApp")
# create spark context with the above configuration
sc = SparkContext(conf=conf)
sc.setLogLevel("ERROR")
# create the Streaming Context from the above spark context with interval size 2 seconds
ssc = StreamingContext(sc, 2)
# setting a checkpoint to allow RDD recovery
ssc.checkpoint("checkpoint_TwitterApp")
# read data from port 9009
dataStream = ssc.socketTextStream("localhost",9009)	


# split each tweet into words
words = dataStream.flatMap(lambda line: line.split(" "))
# filter the words to get only hashtags, then map each hashtag to be a pair of (hashtag,1)
hashtags = words.filter(lambda w: '#' in w).map(lambda x: (x, 1))
# adding the count of each hashtag to its last count
tags_totals = hashtags.updateStateByKey(aggregate_tags_count)
# do processing for each RDD generated in each interval
tags_totals.foreachRDD(process_rdd)
# start the streaming computation
ssc.start()
# wait for the streaming to finish
ssc.awaitTermination()


def aggregate_tags_count(new_values, total_sum):
	return sum(new_values) + (total_sum or 0)
	
def get_sql_context_instance(spark_context):
	if ('sqlContextSingletonInstance' not in globals()):
        globals()['sqlContextSingletonInstance'] = SQLContext(spark_context)
	return globals()['sqlContextSingletonInstance']
def process_rdd(time, rdd):
	print("----------- %s -----------" % str(time))
	try:
    	# Get spark sql singleton context from the current context
    	sql_context = get_sql_context_instance(rdd.context)
    	# convert the RDD to Row RDD
    	row_rdd = rdd.map(lambda w: Row(hashtag=w[0], hashtag_count=w[1]))
    	# create a DF from the Row RDD
    	hashtags_df = sql_context.createDataFrame(row_rdd)
    	# Register the dataframe as table
    	hashtags_df.registerTempTable("hashtags")
    	# get the top 10 hashtags from the table using SQL and print them
    	hashtag_counts_df = sql_context.sql("select hashtag, hashtag_count from hashtags order by hashtag_count desc limit 10")
    	hashtag_counts_df.show()
    	# call this method to prepare top 10 hashtags DF and send them
    	send_df_to_dashboard(hashtag_counts_df)
	except:
    	e = sys.exc_info()[0]
    	print("Error: %s" % e)	
    	

def send_df_to_dashboard(df):
	# extract the hashtags from dataframe and convert them into array
	top_tags = [str(t.hashtag) for t in df.select("hashtag").collect()]
	# extract the counts from dataframe and convert them into array
	tags_count = [p.hashtag_count for p in df.select("hashtag_count").collect()]
	# initialize and send the data through REST API
	url = 'http://localhost:5001/updateData'
	request_data = {'label': str(top_tags), 'data': str(tags_count)}
	response = requests.post(url, data=request_data)    	
        	

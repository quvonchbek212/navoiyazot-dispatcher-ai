import argparse
import uvicorn

def main():
    parser=argparse.ArgumentParser(description='ATIL AI Dispetcher')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',default=8020,type=int)
    args=parser.parse_args()
    uvicorn.run('atil_ai_dispetcher.app:app',host=args.host,port=args.port)

if __name__=='__main__':main()

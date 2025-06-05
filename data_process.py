#!/usr/bin/env python3
import pandas as pd
import scipy.stats as stats
import boto3
import os
import logging

# Configure logging
logging.basicConfig(
    filename='/var/log/data_process.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    try:
        logger.info("Starting data_process.py")
        # Initialize S3 client
        s3 = boto3.client('s3')
        
        # Input and output details
        source_bucket = 'lakshmeesh9731'
        destination_bucket = 'data-9731'
        input_key = 'input.csv'  # Updated path
        output_key = 'output/processed_data.csv'
        
        # Download input file from S3
        local_input = '/tmp/input.csv'
        logger.info(f"Downloading s3://{source_bucket}/{input_key} to {local_input}")
        s3.download_file(source_bucket, input_key, local_input)
        
        # Read and process data
        logger.info("Reading input CSV")
        df = pd.read_csv(local_input)
        
        # Verify 'value' column exists
        if 'value' not in df.columns:
            logger.error("Column 'value' not found in input CSV")
            raise ValueError("Column 'value' not found in input CSV")
        
        # Calculate z-scores using scipy
        logger.info("Calculating z-scores")
        df['z_score'] = stats.zscore(df['value'])
        
        # Save output to local file
        local_output = '/tmp/processed_data.csv'
        logger.info(f"Saving processed data to {local_output}")
        df.to_csv(local_output, index=False)
        
        # Upload output to destination S3 bucket
        logger.info(f"Uploading to s3://{destination_bucket}/{output_key}")
        s3.upload_file(local_output, destination_bucket, output_key)
        
        logger.info(f"Successfully processed data and uploaded to s3://{destination_bucket}/{output_key}")
        
        # Clean up temporary files
        os.remove(local_input)
        os.remove(local_output)
        
    except Exception as e:
        logger.error(f"Error processing data: {str(e)}")
        raise

if __name__ == "__main__":
    main()
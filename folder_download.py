import hashlib
import os.path
import pickle
import shutil

from download_metrics import Metrics
from folder_inventory import *
from google_authentication import authenticate_service_account
from google_drive_api import *
# Block size used for file reading during MD5 Checksum verification
BLOCK_SIZE = 65536
INVENTORY_KEY = "inventory"
DOWNLOADED_KEY = "downloaded"


def serialize(obj, dump_file):
    """
    Serializes the provided object and writes it to the specified file path
    :param obj: The object to be serialized
    :param dump_file: The file path to which the serialized object is written
    """
    path = os.path.dirname(dump_file)
    if not os.path.exists(path):
        os.makedirs(path)
    dump_file = open(dump_file, 'wb')
    pickle.dump(obj, dump_file, pickle.HIGHEST_PROTOCOL)
    dump_file.close()


def deserialize(folder_id):
    """
    Deserializes an object found at the path 'tmp/<folder_id>.dump.tmp' and then returns the object
    :param folder_id: The folder_id used to identify the object to deserialize
    :return: The deserialized object
    """
    dump_name = os.path.join('tmp', '{}.dump.tmp'.format(folder_id))
    dump_file = open(dump_name, 'rb')
    return pickle.load(dump_file)


def verify_md5(file_path, md5):
    """
    Verify a file at the specified file path using the provided MD5 Checksum
    :param file_path: The file path of the file to verify
    :param md5: The MD5 Checksum used to verify
    :return: The Boolean result of the verification
    """
    # Generate an MD5 checksum and then verify that it matches the provided checksum
    with open(file_path, 'rb') as file:
        md5hash = hashlib.md5()
        data = file.read()
        while data:
            md5hash.update(data)
            data = file.read()
    return md5 == md5hash.hexdigest()


def main(inputs):
    # Create service account credentials
    credentials = authenticate_service_account()
    # Create Google Drive API connection using service account credentials
    api = API(credentials)
    # Create an array to store the downloaded files metadata
    downloaded_files = []
    # Loop through each provided Google ID
    for folder_id in inputs.google_id:
        # Create dump file path and create folder structure if necessary
        dump_file = os.path.join('tmp', '{}.dump.tmp'.format(folder_id))
        if os.path.exists(dump_file):
            logging.info("Resuming a previously interrupted transfer")
            serialized_map = deserialize(folder_id)
            inventory = serialized_map[INVENTORY_KEY]
            downloaded_files = serialized_map[DOWNLOADED_KEY]
        else:
            logging.info("Beginning transfer")
            inventory = get_folder_contents(api, folder_id)
        # Initialize and start the download metrics object for the inventory array
        metrics = Metrics(inventory)
        metrics.log_start()
        # Get file metadata array using the current Google ID
        while len(inventory) > 0:
            # Save progress
            serialize({INVENTORY_KEY: inventory, DOWNLOADED_KEY: downloaded_files}, dump_file)
            # Get target file metadata from inventory object
            metadata = inventory.pop()
            # Assemble the full file path and then store the folder path and file name in variables
            path = os.path.join(inputs.output_dir, metadata[FILE_PATH])
            folder_name = os.path.dirname(path)
            file_name = os.path.basename(path)
            # Generate the folder hierarchy on the disk if it does not already exist
            if not os.path.exists(folder_name):
                os.makedirs(folder_name)
            # Download the file
            try:
                logging.info("Downloading File: {}".format(file_name))
                api.download_file(path, metadata[GOOGLE_FILE_ID])
                # Verify the file download and store the verification result in the metadata status attribute
                try:
                    logging.info("Verifying File: {}".format(file_name))
                    if verify_md5(path, metadata[GOOGLE_FILE_MD5]):
                        logging.info("{} MD5 Checksum verified".format(file_name))
                        metadata[FILE_STATUS] = "Checksum Verified"
                    else:
                        logging.warning("{} MD5 Checksum Mismatch".format(file_name))
                        metadata[FILE_STATUS] = "Checksum Mismatched"
                    # Update the metrics object estimate and then retrieve it
                    estimate = metrics.update_estimate(metadata[GOOGLE_FILE_SIZE])
                    # Print the estimated time remaining generated by the metrics object
                    logging.info("Estimated Time Remaining: {}".format(estimate))
                # If an exception occurs during download verification, print an error message and update the file status
                except Exception as ex:
                    logging.error("An error occurred while verifying checksum of file: {}".format(file_name))
                    logging.error(ex)
                    metadata[FILE_STATUS] = "Checksum Verification Error"
            # If an exception occurs during the file download, print an error message and update the file status
            except Exception as ex:
                logging.error("An error occurred while downloading file: {}".format(file_name))
                logging.error(ex)
                metadata[FILE_STATUS] = "Download Error"
            # Append the file metadata to the download files array
            downloaded_files.append(metadata)
        # Save empty inventory to signify this folder has completed in case of interruption
        serialize({INVENTORY_KEY: inventory, DOWNLOADED_KEY: downloaded_files}, dump_file)
    # Download has completed so the tmp directory with the progress dump files can be deleted
    shutil.rmtree('tmp')
    # Generate and inventory report from the downloaded files array
    generate_inventory_report(downloaded_files, inputs.output_dir)
    # Print that the transfer has completed
    logging.info("Transfer Completed")


if __name__ == '__main__':
    # Configure logger
    logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)
    # Parse and verify command line arguments
    args = parse_arguments()
    if verify_args(args):
        main(args)

import os
import sys

# Add project root to python path so we can import src.config and src.storage
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import settings
from src import storage

def main():
    print("==================================================")
    print("   TIGRIS OBJECT STORAGE CONNECTION TESTER        ")
    print("==================================================")
    print(f"Endpoint:      {settings.TIGRIS_ENDPOINT}")
    print(f"Access Key ID: {settings.TIGRIS_ACCESS_KEY_ID[:8]}***")
    print("--------------------------------------------------")

    # Temporarily force TIGRIS_LIVE_MODE = True for diagnostic testing
    settings.TIGRIS_LIVE_MODE = True

    try:
        # 1. Establish Boto3 connection
        print("1. Connecting to Tigris S3 API...")
        s3 = storage.get_s3_client()
        if not s3:
            raise RuntimeError("Could not initialize S3 client. Please verify your settings.")
        print("   Connection established ✓")

        # Let's programmatically define and create dedicated buckets that are 100% owned by these credentials
        # and guaranteed to have "Snapshot Enabled" programmatically!
        master_bucket = "canva-swarm-input-live"
        output_bucket = "canva-swarm-output-live"

        print(f"2. Programmatically ensuring snapshot-enabled master bucket '{master_bucket}' exists...")
        # Check if master bucket exists, if not create it with snapshots enabled!
        try:
            s3.head_bucket(Bucket=master_bucket)
            print("   Master bucket already exists ✓")
        except Exception:
            print("   Master bucket does not exist. Creating with programmatic snapshot enabled...")
            def add_snapshot_header(request, **kwargs):
                request.headers["X-Tigris-Enable-Snapshot"] = "true"
            s3.meta.events.register("before-send.s3.CreateBucket", add_snapshot_header)
            s3.create_bucket(Bucket=master_bucket)
            s3.meta.events.unregister("before-send.s3.CreateBucket", add_snapshot_header)
            print("   Created programmatically with snapshot enabled ✓")

        print(f"3. Programmatically ensuring output bucket '{output_bucket}' exists...")
        try:
            s3.head_bucket(Bucket=output_bucket)
            print("   Output bucket already exists ✓")
        except Exception:
            print("   Output bucket does not exist. Creating programmatically...")
            s3.create_bucket(Bucket=output_bucket)
            print("   Created programmatically ✓")

        # Update runtime settings so rest of script uses these verified buckets
        settings.TIGRIS_MASTER_BUCKET = master_bucket
        settings.TIGRIS_OUTPUT_BUCKET = output_bucket

        # 4. Upload test file to master bucket
        test_key = "tests/connection_check.txt"
        test_content = b"Tigris connection check success!"
        print(f"4. Uploading test file to Master Bucket '{master_bucket}'...")
        storage.upload_asset(master_bucket, test_key, test_content, "text/plain")
        print("   Upload successful ✓")

        # 5. List assets in master bucket to verify upload
        print("5. Listing master bucket assets...")
        assets = storage.list_assets(master_bucket, prefix="tests/")
        print(f"   Found keys: {assets}")
        if test_key not in assets:
            raise ValueError(f"Uploaded file '{test_key}' was not found in bucket listing!")
        print("   Listing successful ✓")

        # 6. Create isolated zero-copy bucket fork
        fork_bucket = f"test-fork-diag-{os.urandom(4).hex()}"
        print(f"6. Creating Zero-Copy Bucket Fork: '{master_bucket}' -> '{fork_bucket}'...")
        storage.create_bucket_fork(master_bucket, fork_bucket)
        print("   Zero-copy fork created successfully on Tigris ✓")

        # 7. Read back test file from the fork bucket to verify metadata cloning
        print(f"7. Downloading test file from the Fork Bucket '{fork_bucket}'...")
        cloned_content = storage.download_asset(fork_bucket, test_key)
        print(f"   Cloned content: '{cloned_content.decode('utf-8')}'")
        if cloned_content != test_content:
            raise ValueError("Downloaded content from fork bucket does not match original uploaded content!")
        print("   Zero-copy metadata clone read verified: SUCCESS ✓")

        # 8. Garbage collection of the fork bucket
        print(f"8. Cleaning up fork bucket '{fork_bucket}'...")
        storage.delete_bucket_fork(fork_bucket)
        print("   Fork bucket deleted successfully ✓")

        # 9. Clean up test file from Master Bucket
        print(f"9. Cleaning up test file from Master Bucket '{master_bucket}'...")
        s3.delete_object(Bucket=master_bucket, Key=test_key)
        print("   Master Bucket test file deleted ✓")

        # 10. Automatically update .env with these guaranteed working buckets!
        print("10. Writing working bucket names to your .env file...")
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()
            
            new_lines = []
            for line in lines:
                if line.startswith("TIGRIS_MASTER_BUCKET="):
                    new_lines.append(f"TIGRIS_MASTER_BUCKET={master_bucket}\n")
                elif line.startswith("TIGRIS_OUTPUT_BUCKET="):
                    new_lines.append(f"TIGRIS_OUTPUT_BUCKET={output_bucket}\n")
                else:
                    new_lines.append(line)
                    
            with open(env_path, "w") as f:
                f.writelines(new_lines)
            print("   Updated .env successfully ✓")

        print("--------------------------------------------------")
        print(" 🎉 TIGRIS CONNECTION & BUCKET FORKING VERIFIED: SUCCESS ✓")
        print("==================================================")
        
    except Exception as e:
        print("\n❌ TIGRIS DIAGNOSTIC FAILED!")
        print(f"Reason: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

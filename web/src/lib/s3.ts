import {
  S3Client,
  GetObjectCommand,
  PutObjectCommand,
  ListObjectsV2Command,
  CopyObjectCommand,
  HeadObjectCommand,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { awsClientConfig } from "./aws";

let client: S3Client | null = null;

export function getS3(): S3Client {
  if (!client) client = new S3Client(awsClientConfig());
  return client;
}

export const MASTER_BUCKET =
  process.env.S3_MASTER_BUCKET || "omniswarm-master-assets";
export const OUTPUT_BUCKET =
  process.env.S3_OUTPUT_BUCKET || "omniswarm-localized-output";

/** Presigned GET URL so the browser can stream private S3 media directly. */
export async function presignGet(
  bucket: string,
  key: string,
  expiresIn = 3600
): Promise<string> {
  return getSignedUrl(getS3(), new GetObjectCommand({ Bucket: bucket, Key: key }), {
    expiresIn,
  });
}

/** Presigned PUT URL so the browser can upload master assets directly to S3. */
export async function presignPut(
  bucket: string,
  key: string,
  contentType: string,
  expiresIn = 3600
): Promise<string> {
  return getSignedUrl(
    getS3(),
    new PutObjectCommand({ Bucket: bucket, Key: key, ContentType: contentType }),
    { expiresIn }
  );
}

export async function listKeys(bucket: string, prefix = ""): Promise<string[]> {
  const out = await getS3().send(
    new ListObjectsV2Command({ Bucket: bucket, Prefix: prefix })
  );
  return (out.Contents ?? []).map((o) => o.Key!).filter(Boolean);
}

/** Server-side copy within/between S3 buckets (no bytes flow through Vercel). */
export async function copyObject(
  srcBucket: string,
  srcKey: string,
  destBucket: string,
  destKey: string,
  contentType?: string
): Promise<void> {
  const copySource = `${srcBucket}/${srcKey
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;
  await getS3().send(
    new CopyObjectCommand({
      Bucket: destBucket,
      Key: destKey,
      CopySource: copySource,
      ...(contentType
        ? { ContentType: contentType, MetadataDirective: "REPLACE" }
        : {}),
    })
  );
}

export async function objectExists(bucket: string, key: string): Promise<boolean> {
  try {
    await getS3().send(new HeadObjectCommand({ Bucket: bucket, Key: key }));
    return true;
  } catch {
    return false;
  }
}

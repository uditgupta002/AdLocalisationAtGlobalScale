/**
 * Centralized AWS credential resolution.
 *
 * IMPORTANT: Vercel runs serverless functions on AWS Lambda, which already
 * populates the reserved `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
 * variables with Vercel's own execution-role credentials. To talk to *our*
 * Aurora DSQL cluster and S3 buckets we therefore read app-scoped variables
 * (`APP_AWS_*`) and pass them explicitly to every AWS SDK client instead of
 * relying on the default provider chain.
 */
export function getRegion(): string {
  return process.env.APP_AWS_REGION || "us-east-1";
}

export function getCredentials() {
  const accessKeyId = process.env.APP_AWS_ACCESS_KEY_ID;
  const secretAccessKey = process.env.APP_AWS_SECRET_ACCESS_KEY;
  if (!accessKeyId || !secretAccessKey) {
    throw new Error(
      "Missing AWS credentials: set APP_AWS_ACCESS_KEY_ID and APP_AWS_SECRET_ACCESS_KEY"
    );
  }
  return { accessKeyId, secretAccessKey };
}

export function awsClientConfig() {
  return {
    region: getRegion(),
    credentials: getCredentials(),
  };
}

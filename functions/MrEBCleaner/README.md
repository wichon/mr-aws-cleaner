# Mr EB Cleaner (Elastic Beanstalk)

Cleans up your Elastic Beanstalk applications versions, deleting older versions except the must recent ones under the defined limit.

## Considerations
* Deployed application versions are excluded from the clean up.
* Versions are also deleted from S3.

## Required Environment Variables
* `application_versions_limit`, the limit of application versions to keep by application 
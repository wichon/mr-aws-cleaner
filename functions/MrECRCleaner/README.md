# Mr ECR Cleaner (EC2 Container Registry)

Cleans up your container repositories, deleting older images except the must recent ones under the defined limit.

## Considerations:
* Untagged images are deleted, as they are not useful outside the repository.
* Images that are referenced by active Task Definition Revisions, will not be deleted.

## Required Environment Variables
* `aws_account_id`, the aws account id associated to the registry
* `ecr_images_limit`, the limit of images to keep by repository
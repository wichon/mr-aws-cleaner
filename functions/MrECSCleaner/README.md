# Mr ECS Cleaner (EC2 Container Service)
============
Cleans up your task definition revisions, deregistering older revisions except the must recent ones under the defined limit.

## Considerations:
* Task definition revisions that are in use by services in any cluster in the region, will not be deleted.

## Required Environment Variables
* `task_definition_revisions_limit`, the limit of revisions to keep by task definition.
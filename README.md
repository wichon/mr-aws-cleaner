# Mr AWS Cleaner

Almost All-Purpose AWS resources cleaner that works like magic!

This tools aims to become like a swiss knife for cleaning unused resources in your AWS Infrastructure.

## Dependencies
* node and npm (Tested with Node v6.5.0 and Npm v3.10.3)
* Serverless framework Version 0.5.6 (Will be migrated to V1 in the future)
  * `npm install -g serverless@0.5.6`

## Set Up
* cd into the repository folder
* Set required environment variables for each function with `serverless variables set` (Check Readme file in each function folder) 
* Init the serverless project with `serverless project init`
  * Each function will act upon the resources within the region of the stage.

## Deploy
Deploy your functions and their triggering events using `serverless dash deploy` (Optional, functions can be run manually also)

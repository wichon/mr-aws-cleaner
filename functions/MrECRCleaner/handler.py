from __future__ import print_function

import os
import json
import time
import boto3
import logging
from datetime import datetime, tzinfo
import dateutil.parser

log = logging.getLogger()
log.setLevel(logging.INFO)

ECR_BATCH_OPS_LIMIT=100
REGION = os.getenv('REGION')
REGISTRY_ID = os.getenv('ECR_REGISTRY_ID')
IMAGES_LIMIT = int(os.getenv('IMAGES_LIMIT'))
ECR_REPOSITORY_URL_BASE="%s.dkr.ecr.%s.amazonaws.com/%s:%s"

ecrClient = boto3.client('ecr', region_name=REGION)
ecsClient = boto3.client('ecs', region_name=REGION)

def list_repository_names(registryId, nextToken = ''):
    repositories = []   
    if nextToken != '':
        repositories = ecrClient.describe_repositories(registryId=registryId, nextToken=nextToken)
    else:
        repositories = ecrClient.describe_repositories(registryId=registryId)
    
    repositoryNames = [repository['repositoryName'] for repository in repositories['repositories']]
    if repositories.has_key('nextToken') and repositories['nextToken'] != None :
        return repositoryNames + list_repository_names(registryId=registryId, nextToken=repositories['nextToken'])
    return repositoryNames

def list_image_ids_by_repository(registryId, repositoryName, untagged, nextToken = ''):
    images = []
    if nextToken != '':
        images = ecrClient.list_images(registryId=registryId, repositoryName=repositoryName, nextToken=nextToken)
    else:
        images = ecrClient.list_images(registryId=registryId, repositoryName=repositoryName)
    
    #filtering untagged/tagged images by hand, as current boto3 version in lambda env doesnt support filtering images
    imageTags = []
    if untagged:
        imageTags = [image for image in images['imageIds'] if not image.has_key('imageTag')]
    else:
        imageTags = [image for image in images['imageIds'] if image.has_key('imageTag')]
    if images.has_key('nextToken') and images['nextToken'] != None :
        return imageTags + list_image_ids_by_repository(registryId=registryId, repositoryName=repositoryName, untagged=untagged, nextToken=images['nextToken'])
    return imageTags

def datetime_to_unix_timestamp(dateTime):
    return (dateTime.replace(tzinfo=None) - datetime(1970, 1, 1)).total_seconds()

# Batch operations in the boto3 ecr client are limited to 100 items per call, 
# so i wrote this small function that brakes an items list in batches and return a list of batches of size batchSize
def list_to_batches(items, batchSize):
    batchesCount = len(items) / batchSize
    reminder = len(items) % batchSize
    return [items[(i*batchSize):(i*batchSize + batchSize)] for i in range(batchesCount + (1 if reminder > 0 else 0))]

def batch_delete_images(registryId, repositoryName, imageIds):    
    failures = 0
    success = 0
    for batch in list_to_batches(imageIds, ECR_BATCH_OPS_LIMIT):
        res = ecrClient.batch_delete_image(registryId=registryId, repositoryName=repositoryName, imageIds=[{'imageDigest': imageId['imageDigest']} for imageId in batch])
        success += len(res['imageIds'])
        if res.has_key('failures') and len(res['failures']) > 0:
            failures += len(res['failures'])
            log.info("The following images failed when trying to deleting them.")
            log.info([{'imageId': failure['imageId'], 'failureCode': failure['failureCode']} for failure in res['failures']])
    
    return {'deleted': success, 'failed': failures}

def list_image_ids_with_age(registryId, repositoryName, imageIds):
    result = []
    for batch in list_to_batches(imageIds, ECR_BATCH_OPS_LIMIT):
        res = ecrClient.batch_get_image(registryId=registryId, repositoryName=repositoryName, imageIds=[{'imageDigest': imageId['imageDigest']} for imageId in batch])
        for image in res['images']:
            manifest = json.loads(image['imageManifest'])
            result.append(      
                {   'imageId': image['imageId'],
                    'timestamp': datetime_to_unix_timestamp(dateutil.parser.parse(json.loads(manifest['history'][0]['v1Compatibility'])['created']))
                }
            )
    return result

def filter_images_to_be_deleted_by_age(imagesWithAge, imagesLimit):
    sortedImagesWithAge = sorted(imagesWithAge, key=lambda v: v['timestamp'], reverse=True)
    sortedImagesWithAgeCount = len(sortedImagesWithAge)
    return [imageWithAge['imageId'] for imageWithAge in sortedImagesWithAge[imagesLimit:sortedImagesWithAgeCount]]

def list_active_task_definitions(nextToken = ''):
    taskDefinitions = []   
    if nextToken != '':
        taskDefinitions = ecsClient.list_task_definitions(status='ACTIVE', nextToken=nextToken)
    else:
        taskDefinitions = ecsClient.list_task_definitions(status='ACTIVE')
    
    taskDefinitionArns = [taskDefinitionArn for taskDefinitionArn in taskDefinitions['taskDefinitionArns']]
    if taskDefinitions.has_key('nextToken') and taskDefinitions['nextToken'] != None :
        return taskDefinitionArns + list_active_task_definitions(nextToken=taskDefinitions['nextToken'])
    return taskDefinitionArns

def list_task_definition_images(taskDefinitionArn):
    taskDefinition = ecsClient.describe_task_definition(taskDefinition=taskDefinitionArn)
    return [containerDefinition['image'] for containerDefinition in taskDefinition['taskDefinition']['containerDefinitions']]

def get_set_images_used_by_task_definitions():
    images = []
    for taskDefinition in list_active_task_definitions():
        time.sleep(0.1)
        images = images + list_task_definition_images(taskDefinition)
    return set(images)

def filter_images_used_in_active_task_definitions(repositoryName, taggedImageIds, taskDefinitionImages):
    return [taggedImageId for taggedImageId in taggedImageIds if (ECR_REPOSITORY_URL_BASE % (REGISTRY_ID, REGION, repositoryName, taggedImageId['imageTag'])) not in taskDefinitionImages]

def filter_images_with_latest_tag(taggedImageIds):
    return [taggedImageId for taggedImageId in taggedImageIds if taggedImageId['imageTag'] != 'latest']

def handler(event, context):
    log.info("************** Starting ECR Images Cleanup, Region: %s - Images Limit: %s **************" % (REGION, IMAGES_LIMIT))
    totalUntaggedImages = 0
    totalTaggedImages = 0
    totalDeletedUntaggedImages = 0
    totalDeletedTaggedImages = 0

    log.info("Getting task definition active images ...")
    taskDefinitionImages = get_set_images_used_by_task_definitions()
    log.info("Retrieved %s images used by active task definitions." % len(taskDefinitionImages))

    for repositoryName in list_repository_names(registryId=REGISTRY_ID):
        log.info("Cleaning images from repository: %s" % repositoryName)

        # Removing untagged images as they are not usable beyong the repository
        untaggedImageIds = list_image_ids_by_repository(registryId=REGISTRY_ID, repositoryName=repositoryName, untagged=True)
        untaggedImageIdsCount = len(untaggedImageIds)
        totalUntaggedImages += untaggedImageIdsCount
        log.info("Cleaning (%s) untagged images:" % untaggedImageIdsCount)
        if untaggedImageIdsCount > 0:
            res = batch_delete_images(registryId=REGISTRY_ID, repositoryName=repositoryName, imageIds=untaggedImageIds)
            totalDeletedUntaggedImages += res['deleted']
            log.info("Deleted images: %s" % res['deleted'])
        else:
            log.info("There are no untagged images, skipping ...")        

        # Removing tagged images
        taggedImageIds = list_image_ids_by_repository(registryId=REGISTRY_ID, repositoryName=repositoryName, untagged=False)
        taggedImageIdsCount = len(taggedImageIds)
        totalTaggedImages += taggedImageIdsCount
        log.info("Cleaning (%s) Tagged images:" % taggedImageIdsCount)
        if taggedImageIdsCount > IMAGES_LIMIT:
            imagesWithAge = list_image_ids_with_age(registryId=REGISTRY_ID, repositoryName=repositoryName, imageIds=taggedImageIds)   
            # age filter needs to be the first as it returns the needed structure for the rest of the filters         
            taggedImageIdsToDelete = filter_images_to_be_deleted_by_age(imagesWithAge=imagesWithAge, imagesLimit=IMAGES_LIMIT)      
            taggedImageIdsToDelete = filter_images_with_latest_tag(taggedImageIds=taggedImageIdsToDelete)
            taggedImageIdsToDelete = filter_images_used_in_active_task_definitions(repositoryName=repositoryName, taggedImageIds=taggedImageIdsToDelete, taskDefinitionImages=taskDefinitionImages)            
            if len(taggedImageIdsToDelete) > 0:
                res = batch_delete_images(registryId=REGISTRY_ID, repositoryName=repositoryName, imageIds=taggedImageIdsToDelete)
                totalDeletedTaggedImages += res['deleted']
                log.info("Deleted images: %s" % res['deleted'])
            else:
                log.info("There are no suitable tagged images to be deleted, skipping ...")
        else:
            log.info("Tagged images are under %s limit, skipping ..." % IMAGES_LIMIT)
    
        log.info("------------------------------------------------------------------------------")

    log.info("Untagged images Total: %s, Deleted: %s" % (totalUntaggedImages, totalDeletedUntaggedImages))
    log.info("Tagged images Total: %s, Deleted: %s" % (totalTaggedImages, totalDeletedTaggedImages))
    log.info("************** Finished Bye **************")
    return {}
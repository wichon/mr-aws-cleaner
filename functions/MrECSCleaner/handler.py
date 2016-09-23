from __future__ import print_function

import os
import json
import time
import boto3
import logging

log = logging.getLogger()
log.setLevel(logging.INFO)

DESCRIBE_SERVICES_BATCH_LIMIT=10
REGION = os.getenv('REGION')
TASK_DEFINITION_REVISIONS_LIMIT = int(os.getenv('TASK_DEFINITION_REVISIONS_LIMIT'))

ecsClient = boto3.client('ecs', region_name=REGION)

def list_cluster_arns(nextToken = ''):
    response = ecsClient.list_clusters(nextToken=nextToken) if nextToken != '' else ecsClient.list_clusters()
    clusterArns = [clusterArn for clusterArn in response['clusterArns']]
    if response.has_key('nextToken') and response['nextToken'] != None :
        return clusterArns + list_cluster_arns(nextToken=response['nextToken'])
    return clusterArns

def list_services_by_cluster(cluster, nextToken = ''):
    response = ecsClient.list_services(cluster=cluster, nextToken=nextToken) if nextToken != '' else ecsClient.list_services(cluster=cluster)
    serviceArns = [serviceArn for serviceArn in response['serviceArns']]
    if response.has_key('nextToken') and response['nextToken'] != None :
        return serviceArns + list_services_by_cluster(cluster=cluster, nextToken=response['nextToken'])
    return serviceArns

def list_to_batches(items, batchSize):
    batchesCount = len(items) / batchSize
    reminder = len(items) % batchSize
    return [items[(i*batchSize):(i*batchSize + batchSize)] for i in range(batchesCount + (1 if reminder > 0 else 0))]

def list_task_definitions_in_use_by_cluster_services(cluster, services):
    taskDefinitions = []
    for servicesBatch in list_to_batches(services, DESCRIBE_SERVICES_BATCH_LIMIT):
        taskDefinitions += [service['taskDefinition'] for service in ecsClient.describe_services(cluster=cluster,services=servicesBatch)['services']]
    return taskDefinitions

def list_task_definition_families(nextToken = ''):
    response = ecsClient.list_task_definition_families(status='ACTIVE', nextToken=nextToken) if nextToken != '' else ecsClient.list_task_definition_families(status='ACTIVE')
    families = [family for family in response['families']]
    if response.has_key('nextToken') and response['nextToken'] != None :
        return families + list_task_definition_families(nextToken=response['nextToken'])
    return families

def list_task_definitions_by_family(family, nextToken = ''):
    response = ecsClient.list_task_definitions(familyPrefix=family, status='ACTIVE', sort='DESC', nextToken=nextToken) if nextToken != '' else ecsClient.list_task_definitions(familyPrefix=family, status='ACTIVE', sort='DESC')
    taskDefinitionArns = [taskDefinitionArn for taskDefinitionArn in response['taskDefinitionArns']]
    if response.has_key('nextToken') and response['nextToken'] != None :
        return taskDefinitionArns + list_task_definitions_by_family(family=family, nextToken=response['nextToken'])
    return taskDefinitionArns

def filter_recent_task_definition_versions(taskDefinitionsByFamily, taskDefinitionRevisionsLimit):
    result = []
    for i in range(len(taskDefinitionsByFamily)):
        taskDefinitionArnsCount = len(taskDefinitionsByFamily[i]['taskDefinitionArns'])
        if taskDefinitionArnsCount > taskDefinitionRevisionsLimit:
            result.append({
                'taskDefinitionFamily': taskDefinitionsByFamily[i]['taskDefinitionFamily'], 
                'taskDefinitionArns': taskDefinitionsByFamily[i]['taskDefinitionArns'][taskDefinitionRevisionsLimit:taskDefinitionArnsCount]
            })
    return result       

def filter_task_definitions_in_use_by_cluster_services(taskDefinitionsByFamily, taskDefinitionsInUse):
    result = []
    for i in range(len(taskDefinitionsByFamily)):
        taskDefinitionArnsCount = len(taskDefinitionsByFamily[i]['taskDefinitionArns'])
        taskDefinitonArns = [taskDefinitionArn for taskDefinitionArn in taskDefinitionsByFamily[i]['taskDefinitionArns'] if taskDefinitionArn not in taskDefinitionsInUse]
        if taskDefinitonArns > 0:
            result.append({
                    'taskDefinitionFamily': taskDefinitionsByFamily[i]['taskDefinitionFamily'], 
                    'taskDefinitionArns': taskDefinitonArns
                })
    return result

def deregister_task_defintion_revision(taskDefinitionRevisioArn):
    try:
        ecsClient.deregister_task_definition(taskDefinition=taskDefinitionRevisioArn)
        return True
    except:
        log.exception("There was an error when trying to deregister: %s" % (taskDefinitionRevisioArn))
        return False


def handler(event, context):
    log.info("************** Starting ECS Task Definition Revisions Cleanup, Region: %s - Revisions Limit: %s **************" % (REGION, TASK_DEFINITION_REVISIONS_LIMIT))
    totalTaskDefinitionRevisions=0
    totalDeregisteredTaskDefinitionRevisions=0
    taskDefinitionsInUse = []
    taskDefinitionsByFamily = []

    log.info("Getting task definition revisions by family ...")
    taskDefinitionFamilies = list_task_definition_families()    
    for taskDefintionFamily in taskDefinitionFamilies:
        taskDefinitionArns = list_task_definitions_by_family(taskDefintionFamily)
        taskDefinitionsByFamily.append({'taskDefinitionFamily': taskDefintionFamily, 'taskDefinitionArns': taskDefinitionArns})
        totalTaskDefinitionRevisions += len(taskDefinitionArns)    
    log.info("Retrieved %s Task Definition Families spanning %s Task Definition Revisions" % (len(taskDefinitionsByFamily), totalTaskDefinitionRevisions))
    log.info("Filtering Top %s recent Task Definition Revisions, and excluding Task Definition families with %s or less revisions ..." % (TASK_DEFINITION_REVISIONS_LIMIT, TASK_DEFINITION_REVISIONS_LIMIT))
    taskDefinitionsByFamily = filter_recent_task_definition_versions(taskDefinitionsByFamily=taskDefinitionsByFamily, taskDefinitionRevisionsLimit=TASK_DEFINITION_REVISIONS_LIMIT)

    log.info("Getting task definition revisions in use by cluster services ...")
    for clusterArn in list_cluster_arns():
        serviceArns = list_services_by_cluster(cluster=clusterArn)
        taskDefinitionsInUse += list_task_definitions_in_use_by_cluster_services(cluster=clusterArn, services=serviceArns)
    log.info("Retrieved %s Task Definition Revisions in use by cluster services" % len(taskDefinitionsInUse))
    
    log.info("Filtering Task Definition Revisions that are in use by cluster services ...")
    taskDefinitionsByFamily = filter_task_definitions_in_use_by_cluster_services(taskDefinitionsByFamily=taskDefinitionsByFamily, taskDefinitionsInUse=set(taskDefinitionsInUse))

    log.info("Cleaning Task Definition Families ...")
    if len(taskDefinitionsByFamily) > 0:
        for familyTaskDefintions in taskDefinitionsByFamily:
            taskDefinitionRevisionsCount = len(familyTaskDefintions['taskDefinitionArns'])
            log.info("Cleaning %s Task Definitions Revisions from Family: %s" % (taskDefinitionRevisionsCount, familyTaskDefintions['taskDefinitionFamily']))
            for taskDefinitionRevisionArn in familyTaskDefintions['taskDefinitionArns']:
                if deregister_task_defintion_revision(taskDefinitionRevisioArn=taskDefinitionRevisionArn):
                    totalDeregisteredTaskDefinitionRevisions+=1
    else:
        log.info("There is no Task Definition Family with more than %s revisions, nothing to do :p." % TASK_DEFINITION_REVISIONS_LIMIT)

    log.info("Task Definition Revisions Total: %s, Deregistered: %s" % (totalTaskDefinitionRevisions, totalDeregisteredTaskDefinitionRevisions))
    log.info("************** Finished Bye **************")
    return {}

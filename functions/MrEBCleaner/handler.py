from __future__ import print_function

import boto3
import logging

log = logging.getLogger()
log.setLevel(logging.INFO)

versionsLimit = 25
region = "us-east-1"

def handler(event, context):
    log.info("************** Starting Applications Cleanup, Region: %s - Application Limit: %s **************" % (region, versionsLimit))

    ebClient = boto3.client('elasticbeanstalk', region_name=region)
    for app in ebClient.describe_applications()['Applications']:
        applicationName = app['ApplicationName']
        log.info("Cleaning application: %s" % applicationName)
        appVersions = ebClient.describe_application_versions(ApplicationName=applicationName)['ApplicationVersions']
        log.info(' * Application Versions: %s' % len(appVersions))

        sortedVersions = sorted(appVersions, key=lambda v: v['DateCreated'], reverse=True)
        sortedVersionsCount = len(sortedVersions)
        listDiff = sortedVersionsCount - versionsLimit;
        if (listDiff > 0):
            versionsToDelete = [version['VersionLabel'] for version in sortedVersions[(sortedVersionsCount-listDiff):sortedVersionsCount]]
            log.info(' *** Suggested Versions to Delete (%s): %s ' % (len(versionsToDelete), versionsToDelete))

            environments = ebClient.describe_environments(ApplicationName=applicationName)['Environments']
            deployedVersions = [environment['VersionLabel'] for environment in environments]
            log.info(' *** Deployed Versions: %s' % deployedVersions)

            finalVersionsToDelete = set(versionsToDelete).difference(set(deployedVersions))
            log.info(' *** Final Versions to delete (%s, excluding the ones that are deployed) : %s' % (len(finalVersionsToDelete), finalVersionsToDelete))

            for version in finalVersionsToDelete:
                log.info(' **** Deleting Version : %s ' % version)
                ebClient.delete_application_version(ApplicationName=applicationName,VersionLabel=version,DeleteSourceBundle=True)

            log.info(' *** Application Versions deleted: %s, bye' % len(finalVersionsToDelete))
        else:
            log.info(' *** Application Versions number %s is lower than the limit %s, no need to clean up, bye.' % (sortedVersionsCount, versionsLimit))

        log.info("------------------------------------------------------------------------------")
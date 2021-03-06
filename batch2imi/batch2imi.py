import glob
import os
import argparse
import logging
import csv
import re
import sys
import pprint

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

argparser = argparse.ArgumentParser()
argparser.add_argument("TOPFOLDER")
argparser.add_argument("OUTPUT", help="The base name of the CSV file(s). Example: mybatch. The file extension and index numbers will be appended automatically. E.g. mybatch.csv or for several batches, when using --max-batch-size mybatch-0001.csv, mybatch-0002.csv, mybatch-0003.csv etc.")
argparser.add_argument("PARENTID")
argparser.add_argument("--remote-path", help="Example: /mnt/ingest/myingestbatch/")
argparser.add_argument("--parent-cmodel", default="islandora:compoundCModel", help="default: 'islandora:compoundCModel'")
argparser.add_argument("--child-cmodel", default="islandora:sp_large_image_cmodel", help="default: 'islandora:sp_large_image_cmodel'")
argparser.add_argument("--max-batch-size", type=int, help="Example: 5000. Rounds up to the nearest compound object.")
args = argparser.parse_args()

TOPFOLDER = args.TOPFOLDER

sourceFolder = TOPFOLDER.strip().strip('/')

findDatastreamsChild = ['OBJ','JP2','MODS', 'TN', 'LARGE_JPG', 'OCR', 'HOCR', 'JPG']
findDatastreamsParent = ['TN', 'OCR', 'MODS']
PARENT_TYPE = args.parent_cmodel
CHILD_TYPE = args.child_cmodel
OUTPUT_FILENAME_BASE = os.path.abspath(args.OUTPUT)

def getSubDirs(directory):
    level1 = glob.glob(directory + '/*')
    parents = []
    for filename in level1:
        if os.path.isdir(filename):
            parents.append(filename)
    parents.sort()
    return parents

def getDatastreams(objectDir, findDatastreams):
    datastreams = {}
    for datastreamType in findDatastreams:
        datastreamInstances = glob.glob(objectDir  + '/' + datastreamType + '.*')
        datastreamInstances.sort()
        if len(datastreamInstances) < 1:
            logging.error("No instances of %s datastream in %s" % (datastreamType, objectDir))
        else:
            if len(datastreamInstances) > 1:
                logging.warning("More than one instances of %s datastream in %s. Arbitrarily picking %s." % (datastreamType, objectDir, datastreamInstances[0]))
            datastreamFileName = datastreamInstances[0]
            if args.remote_path is not None:
                datastreamFileName = re.sub("^\.\/", args.remote_path, datastreamFileName)
            datastreams[datastreamType] = datastreamFileName
    return datastreams

class CompoundObject():
    def __init__(self, parent):
        self.data = {
            'path': parent,
            'datastreams': [],
            'CMODEL': PARENT_TYPE,
            'children': [],
        }
        self.data['datastreams'] = getDatastreams(parent, findDatastreamsParent)
        children_s = getSubDirs(parent)
        for child in children_s:
            childData = {
                'path': child,
                'datastreams': [],
                'CMODEL': CHILD_TYPE,
            }
            childData['datastreams'] = getDatastreams(child, findDatastreamsChild)
            self.data['children'].append(childData)
    def getParentTabular(self):
        myline = self.data['datastreams']
        myline['path'] = self.data['path']
        myline['CMODEL'] = self.data['CMODEL']
        myline['SEQUENCE'] = 1
        return(myline)
    def getChildrenTabular(self):
        mydata = []
        localIndex = 1
        for child in self.data['children']:
            myline = child['datastreams']
            myline['path'] = child['path']
            myline['CMODEL'] = child['CMODEL']
            myline['SEQUENCE'] = localIndex
            mydata.append(myline)
            localIndex = localIndex + 1
        return mydata
    def getLength(self):
        return len(self.data['children']) + 1 # +1 to account for the parent

class Batch():
    def __init__(self):
        self.object_s = []
    def addObject(self, object):
        self.object_s.append(object)
    def getLength(self):
        length = 0
        for object in self.object_s:
            length = length + object.getLength()
        return length
    def getImiBatch(self):
        # Assuming that all objects in the batch are a compound of some kind
        myData = []
        # Get all the objects and put them into a giant table in tabular format
        for object in self.object_s:
            myParentLine = object.getParentTabular()
            myData.append(myParentLine)
            for child in object.getChildrenTabular():
                myChildLine = child
                myData.append(myChildLine)

        # Assign parents by their respective line number
        # Naive approach:
        #   Scan down the list (in order)
        #   If parent, set following parent ids to that line number
        #   If child, use the last parent id set via that method.
        globalIndex = 1 # Start at 1
        globalIndex = globalIndex + 1 # Plus 1 to account for the header line
        currentParentGlobalIndexNumber = None
        for myLine in myData:
            myLine['globalIndex'] = globalIndex
            myLine['A_PARENT'] = None
            if myLine['CMODEL'] == PARENT_TYPE:
                currentParentGlobalIndexNumber = globalIndex
                myLine['A_PARENT'] = args.PARENTID
            else:
                myLine['A_PARENT'] = currentParentGlobalIndexNumber
            globalIndex = globalIndex + 1
        return myData

def writeCsvFile(table, fieldnames, fileName):
    with open(fileName, 'w', newline='') as csvfile:
        csvWriter = csv.DictWriter(csvfile, fieldnames=fieldnames)
        csvWriter.writeheader()
        for line in table:
            csvWriter.writerow(line)

def getColumnNames(table):
    csvFieldsSet = set()
    for line in table:
        csvFieldsSet.update(line.keys())
    fieldnames = list(csvFieldsSet)
    fieldnames.sort()
    return fieldnames

def breakUpBatch(table, maxBatchSize):
    batches = []
    batches.append([])
    batchIndex = 0
    lineNum = 1
    for myLine in table:
        if lineNum > maxBatchSize and myLine['CMODEL'] == PARENT_TYPE:
            batches.append([])
            batchIndex = batchIndex + 1
        batches[batchIndex].append(myLine)
        lineNum = lineNum + 1
        
    return batches

if __name__ == '__main__':
    os.chdir(sourceFolder)
    parent_s = getSubDirs('.')
    batch = Batch()
    for parent in parent_s:
        compoundObject = CompoundObject(parent)
        batch.addObject(compoundObject)
    table = batch.getImiBatch()

    fieldnames = getColumnNames(table)
    if args.max_batch_size is not None:
        subBatches = breakUpBatch(table, args.max_batch_size)
        subBatchIndex = 1
        for subBatch in subBatches:
            outputFileName = "%s-%04d.csv" % (OUTPUT_FILENAME_BASE, subBatchIndex)
            logging.info("Writing to: %s" % outputFileName)
            writeCsvFile(subBatch, fieldnames, outputFileName)
            subBatchIndex = subBatchIndex + 1
    else:
        outputFileName = "%s.csv" % OUTPUT_FILENAME_BASE
        logging.info("Writing to: %s" % outputFileName)
        writeCsvFile(table, fieldnames, outputFileName)

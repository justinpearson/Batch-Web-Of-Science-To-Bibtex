from argparse import ArgumentParser
from wos import WosClient
import wos.utils
import sys
import os
import math
import pdb 
import csv
from suds import WebFault
from bs4 import BeautifulSoup
import shelve

def wos_login(username,password):
    print('Authenticating to WoS...')
    ntries = 0
    while True:
        try:
            ntries += 1
            cli = WosClient(username,password,lite=True)
            print('Connecting attempt # {}'.format(ntries))
            cli.connect()
            break
        except WebFault as e:
            print("WebFault error({0}): {1}".format(e.errno, e.strerror))
            print('Sleeping for 1 sec, then trying again...')
            time.sleep(1) 
    print("Authenticated!")
    return cli


def get_queries(f):
    # Construct a sequence of WoS queries from file of author information 'f'. 
    # Modify this if your datafile isn't CSV or you're not from Santa Barbara :)
    
    for nline,line in enumerate(csv.reader(open(f,'rU'))):
        print('\n')

        if nline == 0:  # header
            ifirst = line.index('First Name')
            ilast = line.index('Last Name')
            continue 

        # wipe out unicode weirdness, sry
        firstname,lastname = [''.join(x for x in line[i] if x.isalpha() or x.isspace()) for i in [ifirst,ilast]]
        if len(firstname)>0:
            firstlet = firstname[0] + '*'
        else:
            firstlet = ''
        query = ('AU=' + lastname + ' ' + firstlet + ' AND AD=Santa Barbara')
        print('CSV line {}, Query: {}'.format(nline,query))
        yield query


def robust_search(cli,query,count=1,offset=1):
    # Use the wos client 'cli' to search the WoS for 'query', 
    # retrying if the SOAP server returns an error, like from
    # throttling.
    #
    # http://ipscience-help.thomsonreuters.com/wosWebServicesLite/bandwidthThrottlingGroup/bandwidthThrottling.html
    ntries = 0
    while True:
        try: 
            ntries += 1
            print('Attempt # {}...'.format(ntries))
            xml = cli.search(query=query, count=count, offset=offset, raw=True)
            print('cli.search success!')
            break
        except WebFault as e:
            print("WebFault error({0}): {1}".format(e.errno, e.strerror))
            print('Sleeping for 1 sec, then trying again...')
            time.sleep(1)     
    return xml


def xml_to_dicts(xml):
    # Parse a WoS search result's XML to make a list of nice flat dicts.
    # (Using raw=False in cli.search returns a messy suds searchResults object.
    #  Sadly it is hard to navigate because it shuffles the order of its fields each time.
    #  The XML is easier.)
    #
    # http://ipscience-help.thomsonreuters.com/wosWebServicesLite/dataReturnedGroup/dataReturned.html
    # http://ipscience-help.thomsonreuters.com/inCites2Live/indicatorsGroup/aboutHandbook/appendix/documentTypes.html

    soup = BeautifulSoup(xml,'html.parser')
    records = soup.find_all('records')
    print('Parsing {} records...'.format(len(records)))
    outlist = []
    for r in records:  # r is a beautifulsoup tag

        d = {}
        d['uid'] = r('uid')[0].text
        labs = r.find_all('label')
        for l in labs:
            vals = []
            t = l.nextSibling
            while True:
                if t is None:
                    break
                elif t.name == 'value':
                    vals.append(t.text)
                elif t.name == 'label':
                    break
                t = t.nextSibling
            vals = list(set(vals))  # unique
            if len(vals) == 0:
                d[l.text] = ''
            elif len(vals) == 1:
                d[l.text] = vals[0]
            else:
                d[l.text] = vals            

        # Sanitize: for each value, if it's a list (instead of a unicode or str),
        # toss every subsequent value, unless the key is Authors, in which case
        # join w/ 'and' between. For example, sometimes WoS has multipel Doctypes:
        # lame.
        for k,v in d.iteritems():
            if isinstance(v,list):
                d[k] = v[0] if k != 'Authors' else ' and '.join(v)

        outlist.append(d)
    return outlist


def dict_to_bibtex(d):
    # Make bibtex entry from it.
    # Bibtex types:
    # http://bib-it.sourceforge.net/help/fieldsAndEntryTypes.php

    doctype = d['Doctype']

    if doctype == 'Article':

        bib = '@article{'

        if 'uid'                    in d:  bib += (              d['uid']                   + ',\n')
        if 'Authors'                in d:  bib += ('author={'  + d['Authors']               + '},\n')
        if 'Title'                  in d:  bib += ('title={'   + d['Title']                 + '},\n')
        if 'SourceTitle'            in d:  bib += ('journal={' + d['SourceTitle']           + '},\n')
        if 'Published.BiblioYear'   in d:  bib += ('year={'    + d['Published.BiblioYear']  + '},\n')
        if 'Volume'                 in d:  bib += ('volume={'  + d['Volume']                + '},\n')
        if 'Issue'                  in d:  bib += ('number={'  + d['Issue']                 + '},\n')
        if 'Pages'                  in d:  bib += ('pages={'   + d['Pages']                 + '},\n')
        if 'Published.BiblioDate'   in d:  bib += ('month={'   + d['Published.BiblioDate']  + '},\n')

        bib += '}\n'
        return bib

    elif doctype == 'Proceedings Paper' or doctype == 'Meeting Abstract':

        bib = '@inproceedings{'

        if 'uid'                    in d:  bib += (                   d['uid']                  + ',\n')
        if 'Authors'                in d:  bib += ('author={'       + d['Authors']              + '},\n')
        if 'Title'                  in d:  bib += ('title={'        + d['Title']                + '},\n')
        if 'BookSeriesTitle'        in d:  bib += ('booktitle={'    + d['BookSeriesTitle']      + '},\n')
        if 'Published.BiblioYear'   in d:  bib += ('year={'         + d['Published.BiblioYear'] + '},\n')
        if 'Volume'                 in d:  bib += ('volume={'       + d['Volume']               + '},\n')
        if 'Issue'                  in d:  bib += ('number={'       + d['Issue']                + '},\n')
        if 'Pages'                  in d:  bib += ('pages={'        + d['Pages']                + '},\n')
        if 'Published.BiblioDate'   in d:  bib += ('month={'        + d['Published.BiblioDate'] + '},\n')
        if 'BookGroupAuthors'       in d:  bib += ('organization={' + d['BookGroupAuthors']     + '},\n')

        bib += '}\n'
        return bib

    elif doctype == 'Review' or doctype == 'Letter' or doctype == 'Book Review':
        print('Skipping shitty doctype: {}'.format(doctype))
        return None

    else:
        print('Unfamiliar doctype: {}'.format(doctype))
        # print('Pausing to explore it:')
        # pdb.set_trace()
        return None



def main():

    parser = ArgumentParser(description='Batch-query the Web of Science and export to BibTeX.')
    parser.add_argument('-u', '--user', type=str, default=None, help='Web of Science username.')
    parser.add_argument('-p', '--password', type=str, default=None, help='Web of Science password.')
    parser.add_argument('-i', '--input', type=str, default='my.csv', help='Input file parsed by get_queries().')
    parser.add_argument('-o', '--output', type=str, default='my.bib', help='Output BibTeX file to create.')
    parser.add_argument('-c', '--cache', type=str, default='wos.shelf', help='Shelve-format cache of query data.')
    args = parser.parse_args()


    db = shelve.open(args.cache) 
    if os.path.exists(args.output): os.remove(args.output)
    cli = wos_login(args.user,args.password)
    for query in get_queries(f=args.input):
        num_have_already = len(db[query]) if query in db else 0
        print('Have {} biblios locally already in shelf file {}'.format(num_have_already,args.cache))
        num_results = cli.search(query,count=0).recordsFound
        print("{} biblios available online.".format(num_results))
        if num_have_already >= num_results:
            print("Looks like we're up to date, skipping.")
            continue
        MAX_PER_QUERY = 100;
        num_retrieves_needed = int(math.ceil(num_results/float(MAX_PER_QUERY)))
        all_dicts_for_this_query = [] 
        for i in range(num_retrieves_needed):
            print('Request {} of {}: Retrieving results {} -- {}...'.format(
                i+1,num_retrieves_needed,MAX_PER_QUERY*i+1,min(num_results,MAX_PER_QUERY*(i+1))))
            xml = robust_search(cli,query,count=MAX_PER_QUERY,offset=MAX_PER_QUERY*i+1)
            dicts = xml_to_dicts(xml)
            all_dicts_for_this_query.extend(dicts)
            for d in dicts:
                bib = dict_to_bibtex(d)
                if bib is not None:
                    with open(args.output,'a') as bibfile: 
                        bibfile.write(bib)
                        # print('Check bibfile for bib:')
                        # print(bib)
                        # pdb.set_trace()
                        # print('ok?')
        db[query] = all_dicts_for_this_query # save all query's dict-records in the shelf.

    print('All done!')
    db.close()
    cli.close()



if __name__ == '__main__':
    # pdb.set_trace()
    main()

#!/bin/bash
namespace="compression-namespace"
# Since Zookeper takes time to start up, we start it beforehand and wait a moment
kubectl apply -n $namespace -f zookeper_manifest.yaml
sleep 21 # wait till zookeeper pod is ready
#Deploy the manifest
kubectl apply -f manifest.yaml
#Check if the api service is going up 
tries=0
kube_command="kubectl get -n $namespace services -ojson | jq ' .items | length'"
while [ $(eval $kube_command) -eq 0 ] ; do
  sleep 20
  $tries++
  if [ $tries -gt 5 ] ; then break; fi
done
# give the workers and the service some time
sleep 25
# set up a connection to the service using port-forwarding 
kubectl port-forward -n $namespace service/apiservice 8080 &
pid=$!
# fetch the compressed file
sleep 3 # Give portforward time to start
curl --silent --show-error  http://localhost:8080 --output compressed 
#tear down the deployment
kill -term $pid
wait $pid
kubectl delete -f manifest.yaml
kubectl delete -n $namespace -f zookeper_manifest.yaml
#inflate the compressed file 
./inflate compressed inflated
# compare the results
[ "$(sha256sum inflated | awk '{print $1}')" = "$(sha256sum worker/odyssey.txt | awk '{print $1}')" ] 

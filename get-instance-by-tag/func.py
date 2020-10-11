import io
import json
import logging

from fdk import response
from datetime import datetime
import oci


def jsonconverter(o):
    return o.strftime("%d/%m/%Y, %H:%M:%S") if isinstance(o, datetime) else o.__dict__


class OCI_Instance:
    def __init__(self, id):
        self.id = id
        self.display_name = ''
        self.ips = []
        self.time_created = datetime.now()
        self.compartment_id = ''
        self.lifecycle_state = ''
        self.defined_tags = ''

    def toJSON(self):
        return json.dumps(self, default=lambda o: jsonconverter(o), sort_keys=True, indent=4)

    def __str__(self):
        return 'OCI_Instance(id="' + self.id + '"' \
            + ', IPs=' + str(self.ips) \
            + ', lifecycle_state="' + self.lifecycle_state + '"' \
            + ', time_created=' + self.time_created.strftime("%d/%m/%Y, %H:%M:%S") \
            + ', compartment_id="' + str(self.compartment_id) + '"' \
            + ')'

    def __lt__(self, other):
        # older than other
        return self.time_created < other.time_created


def handler(ctx, data: io.BytesIO = None):
    instances_result = []
    #logging.getLogger().info("get-instance-by-tag: read and parse configuration")
    try:
        tag_key = (ctx.Config())["TAGKEY"]
        tag_value = (ctx.Config())["TAGVALUE"]
    except (Exception, ValueError) as ex:
        logging.getLogger().info('error reading configuration: ' + str(ex))
        return response.Response(
            ctx, response_data=json.dumps(
                {"Error": "Bad or missing configuration {0}".format(ex)}),
            headers={"Content-Type": "application/json"}
        )

    #logging.getLogger().info("get-instance-by-tag: getting instances")
    try:
        signer = oci.auth.signers.get_resource_principals_signer()
        compute_client = oci.core.ComputeClient(config={}, signer=signer)
        inst = compute_client.list_instances(signer.compartment_id)
    except (Exception, ValueError) as ex:
        logging.getLogger().info('error getting instances: ' + str(ex))
        return response.Response(
            ctx, response_data=json.dumps(
                {"Error": "Unable to fetch instances {0}".format(ex)}),
            headers={"Content-Type": "application/json"}
        )

    #logging.getLogger().info("get-instance-by-tag: filtering instances by tag")
    for i in inst.data:
        # instances_result.append(OCI_Instance(i.id))
        # for tagspaces in defined_tags : owner, schedule, etc
        for namespace in (i.defined_tags).keys():
            # (i.defined_tags)[namespace]="Owner(dict)"
            for tag in ((i.defined_tags)[namespace]).keys():
                # (instances_result[-1]).all_tags.append((tag,
                # ((i.defined_tags)[namespace])[tag]))
                if ((tag_key + "-" + tag_value) == (tag + "-" + ((i.defined_tags)[namespace])[tag])) and (i.lifecycle_state != "TERMINATED"):
                    instances_result.append(OCI_Instance(i.id))
                    (instances_result[-1]).time_created = i.time_created
                    (instances_result[-1]).compartment_id = i.compartment_id
                    (instances_result[-1]).lifecycle_state = i.lifecycle_state
                    (instances_result[-1]).display_name = i.display_name
                    (instances_result[-1]).defined_tags = i.defined_tags
    if len(instances_result) == 0:
        return response.Response(
            ctx, response_data=json.dumps(
                {"Info": "No instances matching tag "+tag_key+":"+tag_value}),
            headers={"Content-Type": "application/json"}
        )

    #logging.getLogger().info("get-instance-by-tag: ordering instances by latest")
    lastUp = instances_result[0]
    for inst_l in instances_result:
        if lastUp < inst_l:
            lastUp = inst_l

    #logging.getLogger().info("get-instance-by-tag: get instance private IP")
    try:
        signer = oci.auth.signers.get_resource_principals_signer()
        virtual_network_client = oci.core.VirtualNetworkClient(
            config={}, signer=signer)

        vnic_attachments = oci.pagination.list_call_get_all_results(
            compute_client.list_vnic_attachments,
            compartment_id=lastUp.compartment_id,
            instance_id=lastUp.id
        ).data
        vnics = [virtual_network_client.get_vnic(
            va.vnic_id).data for va in vnic_attachments]
        for vnic in vnics:
            private_ips_for_vnic = oci.pagination.list_call_get_all_results(
                virtual_network_client.list_private_ips,
                vnic_id=vnic.id).data
            for private_ip in private_ips_for_vnic:
                lastUp.ips.append(private_ip.ip_address)
    except (Exception, ValueError) as ex:
        logging.getLogger().info('error getting IPs information: ' + str(ex))
        return response.Response(
            ctx, response_data=json.dumps(
                {"Error": "Unable to fetch IPs information: {0}".format(ex)}),
            headers={"Content-Type": "application/json"}
        )

    return response.Response(
        ctx,
        response_data=lastUp.toJSON(),
        headers={"Content-Type": "application/json"}
    )

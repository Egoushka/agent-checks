# C2: observe mode always allows and opens a lease
POST {{base_url}}/v1/admit
Authorization: Bearer {{consumer_token}}
Content-Type: application/json
{"consumer":"example-job"}
HTTP 200
[Asserts]
jsonpath "$.decision" == "allow"
jsonpath "$.lease_id" exists
jsonpath "$.lease_id" != null

# T14: no consumer token, no admit
POST {{base_url}}/v1/admit
Content-Type: application/json
{"consumer":"example-job"}
HTTP 401

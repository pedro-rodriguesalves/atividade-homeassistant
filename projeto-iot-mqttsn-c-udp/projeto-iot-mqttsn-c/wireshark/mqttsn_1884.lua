-- Dissector didatico MQTT-SN 1.2 na porta UDP 1884.
-- Salve na pasta Personal Lua Plugins do Wireshark e reinicie o aplicativo.
local p = Proto("mqttsn_lab", "MQTT-SN (Laboratorio)")
local length_short_f = ProtoField.uint8("mqttsn_lab.length_short", "Length", base.DEC)
local length_long_f = ProtoField.uint16("mqttsn_lab.length_long", "Length", base.DEC)
local type_f = ProtoField.uint8("mqttsn_lab.type", "MsgType", base.HEX, {
    [0x00]="ADVERTISE", [0x01]="SEARCHGW", [0x02]="GWINFO",
    [0x04]="CONNECT", [0x05]="CONNACK", [0x0A]="REGISTER",
    [0x0B]="REGACK", [0x0C]="PUBLISH", [0x0D]="PUBACK",
    [0x16]="PINGREQ", [0x17]="PINGRESP", [0x18]="DISCONNECT"
})
local flags_f = ProtoField.uint8("mqttsn_lab.flags", "Flags", base.HEX)
local topic_id_f = ProtoField.uint16("mqttsn_lab.topic_id", "TopicId", base.DEC)
local msg_id_f = ProtoField.uint16("mqttsn_lab.msg_id", "MsgId", base.DEC)
local rc_f = ProtoField.uint8("mqttsn_lab.return_code", "ReturnCode", base.HEX)
local payload_f = ProtoField.string("mqttsn_lab.data", "Data")
local topic_name_f = ProtoField.string("mqttsn_lab.topic_name", "TopicName")
p.fields = {length_short_f, length_long_f, type_f, flags_f, topic_id_f, msg_id_f, rc_f, payload_f, topic_name_f}
local names = {[0x04]="CONNECT", [0x05]="CONNACK", [0x0A]="REGISTER", [0x0B]="REGACK", [0x0C]="PUBLISH", [0x0D]="PUBACK", [0x16]="PINGREQ", [0x17]="PINGRESP", [0x18]="DISCONNECT"}

function p.dissector(buf, pinfo, tree)
    local size = buf:len()
    if size < 2 then return 0 end
    local extended = buf(0,1):uint() == 1
    local header = extended and 4 or 2
    if size < header then return 0 end
    local total = extended and buf(1,2):uint() or buf(0,1):uint()
    if total ~= size then return 0 end
    local tpos = extended and 3 or 1
    local msg_type = buf(tpos,1):uint()
    local body = header
    pinfo.cols.protocol = "MQTT-SN"
    pinfo.cols.info = "MQTT-SN " .. (names[msg_type] or string.format("Type 0x%02X", msg_type))
    local node = tree:add(p, buf(), "MQTT-SN 1.2")
    if extended then node:add(length_long_f, buf(1,2)) else node:add(length_short_f, buf(0,1)) end
    node:add(type_f, buf(tpos,1))
    if msg_type == 0x04 and size >= body+4 then
        node:add(flags_f, buf(body,1))
        node:add(payload_f, buf(body+4,size-body-4))
    elseif msg_type == 0x05 and size >= body+1 then
        node:add(rc_f, buf(body,1))
    elseif msg_type == 0x0A and size >= body+4 then
        node:add(topic_id_f, buf(body,2))
        node:add(msg_id_f, buf(body+2,2))
        node:add(topic_name_f, buf(body+4,size-body-4))
    elseif msg_type == 0x0B and size >= body+5 then
        node:add(topic_id_f, buf(body,2))
        node:add(msg_id_f, buf(body+2,2))
        node:add(rc_f, buf(body+4,1))
    elseif msg_type == 0x0C and size >= body+5 then
        node:add(flags_f, buf(body,1))
        node:add(topic_id_f, buf(body+1,2))
        node:add(msg_id_f, buf(body+3,2))
        if size > body+5 then node:add(payload_f, buf(body+5,size-body-5)) end
    end
    return size
end
DissectorTable.get("udp.port"):add(1884, p)

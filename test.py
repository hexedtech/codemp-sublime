import bindings.codemp_client
import asyncio

HOST = "http://alemi.dev:50051"
LOCAL_HOST = "http://[::1]:50051"

async def get_handle(host):
    return await bindings.codemp_client.connect(host)

async def get_id(handle):
    return await handle.get_id()

async def create_buffer(handle):
	return await handle.create("test.py") 

async def main():
    handle = await bindings.codemp_client.connect(HOST)
    print("Client Handle: ", handle)
    id = await handle.get_id()
    print("Client ID: ", id)
    buffer_created = await create_buffer(handle)
    print("buffer_created: ", buffer_created)



asyncio.run(main())

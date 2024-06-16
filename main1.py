from fastapi import FastAPI, APIRouter, Depends, HTTPException, Form, UploadFile, File
from pydantic import BaseModel
import boto3
import uuid
from boto3.dynamodb.conditions import Key
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime
import re
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

app = FastAPI()

# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
client_credentials_table = dynamodb.Table('Client_Credentials')
employee_table= dynamodb.Table('Employees')

# Custom OAuth2PasswordBearer to bypass default behavior
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/peoplesuite/apis/token")

# Initialize S3 client
s3 = boto3.client('s3')
bucket_name = 'clientsphotos'

# Define Pydantic models
class Token(BaseModel):
    access_token: str
    token_type: str

class EmployeeProfileBase(BaseModel):
    first_name: str
    last_name: str
    start_date: str
    country: str

class EmployeeProfileCreate(EmployeeProfileBase):
    pass

class EmployeeProfile(EmployeeProfileBase):
    employee_id: str

class PhotoResponse(BaseModel):
    message: str
    filename: str

# Utility function to verify token
def verify_token(token: str = Depends(oauth2_scheme)):
    response = client_credentials_table.scan(FilterExpression=Key('access_token').eq(token))
    if 'Items' not in response or len(response['Items']) == 0:
        raise HTTPException(status_code=401, detail="Invalid token")
    return True

# Routes
@app.post("/peoplesuite/apis/token", response_model=Token)
async def generate_token(
    grant_type: str = Form(...),
    client_id: str = Form(...),
    client_secret: str = Form(...)
):
    if grant_type != "client_credentials":
        raise HTTPException(status_code=400, detail="Invalid grant type")
    
    response = client_credentials_table.get_item(Key={'client_id': client_id})
    if 'Item' not in response or response['Item']['client_secret'] != client_secret:
        raise HTTPException(status_code=400, detail="Invalid client_id or client_secret")
    
    access_token = str(uuid.uuid4())
    client_credentials_table.update_item(
        Key={'client_id': client_id},
        UpdateExpression="set access_token = :t",
        ExpressionAttributeValues={':t': access_token}
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/peoplesuite/apis/employees/{employee_id}/profile", dependencies=[Depends(verify_token)])
async def create_employee_profile(
    employee_id: str,
    data: EmployeeProfileCreate
):
    try:
        response = employee_table.put_item(
            Item={
                'EmployeeID': employee_id,
                'FirstName': data.first_name,
                'LastName': data.last_name,
                'StartDate': data.start_date,
                'Country': data.country
            }
        )
        return {"employee_id": employee_id, **data.dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/peoplesuite/apis/employees/{employee_id}/profile", dependencies=[Depends(verify_token)])
async def get_employee_profile(employee_id: str):
    try:
        response = employee_table.get_item(Key={'EmployeeID': employee_id})
        item = response.get('Item')
        if not item:
            raise HTTPException(status_code=404, detail="Employee not found")
        return item
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/peoplesuite/apis/employees/{employee_id}/photo", dependencies=[Depends(verify_token)])
async def upload_employee_photo(employee_id: str, file: UploadFile = File(...)):
    file_extension = file.filename.split('.')[-1] in ("jpg", "jpeg", "png")
    if not file_extension:
        raise HTTPException(status_code=400, detail="Invalid file format")

    try:
        file_content = await file.read()
        s3.upload_fileobj(
            Fileobj=file.file,
            Bucket=bucket_name,
            Key=f"{employee_id}.{file.filename.split('.')[-1]}"  # e.g., employee_id.jpg
        )
        return {"message": "Photo uploaded successfully", "filename": f"{employee_id}.{file.filename.split('.')[-1]}"}
    except (NoCredentialsError, PartialCredentialsTableError) as e:
        raise HTTPException(status_code=500, detail="Could not connect to AWS with the provided credentials")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/peoplesuite/apis/employees/{employee_id}/photo", dependencies=[Depends(verify_token)])
async def get_employee_photo(employee_id: str):
    try:
        photo_url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': f"{employee_id}.jpeg"},
            ExpiresIn=3600
        )
        return {"employee_id": employee_id, "photo_url": photo_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.compute import EC2
from diagrams.aws.database import RDS
from diagrams.aws.network import VPC, InternetGateway, NATGateway
from diagrams.aws.security import SecretsManager
from diagrams.aws.management import SystemsManager
from diagrams.onprem.client import User
from diagrams.programming.framework import Fastapi
from diagrams.generic.compute import Rack
from diagrams.generic.cloud import Cloud

# Generate the architecture diagram
with Diagram("Claim Denial Prevention Architecture", show=False, filename="/Users/varad.naik/Desktop/Claim-denial-Project/architecture/cdp_architecture", direction="LR"):
    analyst = User("Billing Analyst\n(Local Laptop)")
    ssm = SystemsManager("AWS SSM Tunnel\n(Port Forwarding)")
    
    with Cluster("AWS Cloud"):
        secrets = SecretsManager("Secrets Manager\n(DB Credentials)")
        
        with Cluster("VPC (cdp-vpc)"):
            with Cluster("Public Subnet"):
                igw = InternetGateway("Internet Gateway")
                nat = NATGateway("NAT Gateway")
                igw - nat
            
            with Cluster("Private App Subnet"):
                ec2 = EC2("EC2 Instance\n(No Public IP)")
                app = Fastapi("Streamlit UI & FastAPI")
                ec2 - app
            
            with Cluster("Private DB Subnet"):
                rds = RDS("PostgreSQL\n(claim_history)")
                
        # Internal Routing
        ec2 >> Edge(label="Port 5432") >> rds
        ec2 >> Edge(label="Fetch Auth") >> secrets
        ec2 >> Edge(label="Outbound Internet") >> nat
        
    with Cluster("External APIs / Services"):
        supabase = Cloud("Supabase\n(Auth & JWT)")
        databricks = Cloud("Databricks\n(Gold Tables)")
        openai = Cloud("OpenAI GPT-4o\n(LLM Extraction)")

    # User flows
    analyst >> Edge(label="HTTPS (localhost:8501)") >> ssm >> ec2
    nat >> Edge(label="HTTPS") >> supabase
    nat >> Edge(label="HTTPS") >> databricks
    nat >> Edge(label="HTTPS") >> openai

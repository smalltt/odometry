pipeline {
    agent {
        dockerfile {
        args '--runtime=nvidia -v /datasets:/datasets -v /weights:/weights'
        }
    }
    stages {
        stage('Build') {
            steps {
                echo 'Building..'
                sh 'rm -rf weights'
                sh 'ln -s /weights weights'
            }
        }
        stage('Test') {
            steps {
                echo 'Testing..'
                sh 'nvidia-smi'
                sh '/home/odometry/miniconda/bin/activate /home/odometry/miniconda/envs/odometry'
                sh '/home/odometry/miniconda/envs/odometry/bin/python -m unittest discover -s tests'
            }
        }
    }
}